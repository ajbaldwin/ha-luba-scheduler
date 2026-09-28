"""Shadow comparison against the YAML FSM, and luba.import_yaml_state (design Q4/Q10, P3/P4)."""
import pytest
import voluptuous as vol
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.exceptions import ServiceValidationError

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from .world import build, fsm, later, local, put, settle, tick

YAML_FSM = "input_select.yaml_fsm"
SUNDAY = (2026, 9, 27, 10, 0)                          # no group: nothing of the port's moves


def _attrs(hass):
    return hass.states.get(c.STATE_ENTITY_ID).attributes


def _lines(hass):
    lines = []
    hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, lambda e: lines.append(e.data["message"]))
    return lines


async def _shadow(hass, freezer, yaml_state="Idle", **kw):
    hass.states.async_set(YAML_FSM, yaml_state)
    return await build(hass, freezer, active=False, at=local(*SUNDAY),
                       **{c.CONF_YAML_STATE: YAML_FSM}, **kw)


# ---- comparison ----------------------------------------------------------------------------

async def test_no_comparison_attributes_unless_configured(hass, freezer):
    await build(hass, freezer, active=False)
    assert "yaml_state" not in _attrs(hass) and "diverged" not in _attrs(hass)


async def test_agreement_then_a_lasting_divergence_is_logged_once_and_cleared(hass, freezer):
    _world, entry = await _shadow(hass, freezer)
    lines = _lines(hass)
    assert _attrs(hass)["yaml_state"] == "Idle" and _attrs(hass)["diverged"] is False

    hass.states.async_set(YAML_FSM, "Scheduled")
    await settle(hass, entry, freezer)
    assert _attrs(hass)["diverged"] is True and _attrs(hass)["diverged_since"]
    await tick(hass, entry, freezer, later(minutes=4))
    assert not any(line.startswith("shadow: diverged") for line in lines)
    await tick(hass, entry, freezer, later(minutes=2))
    assert [line for line in lines if line.startswith("shadow: diverged")] == [
        "shadow: diverged from the YAML for 5 min — port Idle, YAML Scheduled"]

    hass.states.async_set(YAML_FSM, "Idle")
    await settle(hass, entry, freezer)
    assert _attrs(hass)["diverged"] is False and _attrs(hass)["diverged_since"] is None
    assert lines[-1] == "shadow: agrees with the YAML again (Idle) after 6 min"


async def test_a_short_blip_is_not_logged(hass, freezer):
    _world, entry = await _shadow(hass, freezer)
    lines = _lines(hass)
    hass.states.async_set(YAML_FSM, "Running")
    await tick(hass, entry, freezer, later(minutes=1))
    hass.states.async_set(YAML_FSM, "Idle")
    await tick(hass, entry, freezer, later(minutes=10))
    assert not any(line.startswith("shadow:") for line in lines)


async def test_yaml_charging_equals_port_paused(hass, freezer):
    world, entry = await _shadow(hass, freezer, yaml_state="Charging")
    world.hold_docked("Back")
    put(entry, state=F.PAUSED)
    await settle(hass, entry, freezer)
    assert _attrs(hass)["diverged"] is False


async def test_an_unavailable_yaml_entity_compares_nothing(hass, freezer):
    await _shadow(hass, freezer, yaml_state="unavailable")
    assert _attrs(hass)["yaml_state"] is None and _attrs(hass)["diverged"] is None


# ---- import ---------------------------------------------------------------------------------

async def _import(hass, **data):
    await hass.services.async_call(c.DOMAIN, "import_yaml_state", data, blocking=True)


async def test_import_is_refused_outside_shadow(hass, freezer):
    await build(hass, freezer)                                  # active
    with pytest.raises(ServiceValidationError):
        await _import(hass, fsm_state="Idle")


async def test_import_copies_the_yaml_state(hass, freezer):
    world, entry = await build(hass, freezer, active=False, at=local(*SUNDAY))
    world.hold_docked("Back", battery=60)
    lines = _lines(hass)
    await _import(hass, fsm_state="Charging", prior_state="", error_from="unknown",
                  session_start="2026-09-26 14:05:00", session_battery_start="98.0",
                  session_work_area="Back", session_recharge_count="1",
                  session_abort_reason="Weather: rain", active_group="B",
                  scheduled_group="B", evaluated_at="2026-09-26 08:45:00",
                  cuts_a="1", cuts_b="0", last_counted_cut="A|2026-09-22",
                  last_logged_cut="Group A|2026-09-22", angle_1="48", spacing="29",
                  cutting_height="70", cuts_per_group="3", auto_start="off")
    await settle(hass, entry, freezer)
    s = entry.runtime_data.store
    assert fsm(entry) == F.PAUSED                               # Charging → Paused (M5)
    assert s.session.start == local(2026, 9, 26, 14, 5).isoformat()     # aware, local
    assert (s.session.battery_start, s.session.recharge_count) == (98.0, 1)
    assert s.session.abort_reason == "Weather: rain" and s.session.active_group == "B"
    assert (s.day.scheduled_group, s.counters.cuts) == ("B", {"A": 1, "B": 0})
    assert s.counters.last_logged_cut == "Group A|2026-09-22"
    assert (s.settings.angle_1, s.settings.spacing, s.settings.cuts_per_group) == (48, 29, 3)
    assert s.settings.auto_start is False
    assert any("-> Paused [imported from the YAML]" in line for line in lines)
    assert "reboot_recover" in entry.runtime_data.dispatcher.handled[-3:]
    assert world.calls == []

    lines.clear()                                               # idempotent
    await _import(hass, fsm_state="Charging", cuts_a="1", session_work_area="Back")
    assert lines[0] == "import_yaml_state: 0 field(s) changed"


async def test_import_treats_the_yaml_sentinels_as_empty(hass, freezer):
    _world, entry = await build(hass, freezer, active=False)
    put(entry, session__start="2026-09-29T08:00:00-07:00", session__battery_start=50.0)
    await _import(hass, session_start="1970-01-01 00:00:00", session_battery_start="unknown")
    s = entry.runtime_data.store
    assert s.session.start == ""                                # the YAML's "no session"
    assert s.session.battery_start == 50.0                     # unreadable: left alone


@pytest.mark.parametrize("data", [{"fsm_state": "Delayed"}, {"scheduled_group": "C"},
                                  {"cuts_per_group": "4"}, {"session_start": "yesterday"}])
async def test_import_rejects_values_the_port_cannot_hold(hass, freezer, data):
    await build(hass, freezer, active=False)
    with pytest.raises(vol.Invalid):
        await _import(hass, **data)


async def test_an_imported_prompt_is_rearmed(hass, freezer):
    """The YAML's own prompt can't be answered here (MOW_* actions), so the heartbeat
    re-prompts with Luba's."""
    world, entry = await build(hass, freezer, active=False)
    await tick(hass, entry, freezer, later(minutes=1))          # 08:41, before the scheduler
    await _import(hass, fsm_state="Awaiting Acknowledgment", scheduled_group="A",
                  evaluated_at="2026-09-29 08:40:00")
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.AWAITING
    assert entry.runtime_data.store.day.ack_deadline
    await tick(hass, entry, freezer, later(minutes=31))
    assert entry.runtime_data.store.day.prompt_id                # Luba's own prompt now
