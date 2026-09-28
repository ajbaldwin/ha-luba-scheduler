"""Smaller invariants carried over from the YAML suite (see tests/TRACEABILITY.md)."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.luba import const as c
from custom_components.luba.dispatcher import ISSUE_OVERFLOW, QUEUE_MAX, Dispatcher
from custom_components.luba.engine import fsm as F

from .world import build, dispatch, fire_action, fsm, later, local, put, settle, tick

TODAY_10 = "2026-09-29T10:00:00-07:00"


async def _awaiting(hass, freezer, **kw):
    world, entry = await build(hass, freezer, **kw)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    return world, entry


# ---- start refusals: danger and the gate, never permission ------------------------------

async def test_a_manual_start_overrides_permission_not_danger(hass, freezer):
    """Optimal off at the tap does not refuse a Start (the owner's call); adverse would."""
    world, entry = await _awaiting(hass, freezer)
    hass.states.async_set("binary_sensor.dry_a", "off")
    await settle(hass, entry, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert len(world.called("mammotion.start_mow")) == 1


@pytest.mark.parametrize(("polarity", "closed", "opened"), [
    (c.GATE_ON_CLOSED, "on", "off"), (c.GATE_ON_OPEN, "off", "on")])
async def test_gate_polarity(hass, freezer, polarity, closed, opened):
    hass.states.async_set("binary_sensor.gate_closed", closed)
    world, entry = await build(hass, freezer, **{c.CONF_GATE_POLARITY: polarity})
    hass.states.async_set("binary_sensor.gate_closed", closed)
    await tick(hass, entry, freezer, later(minutes=5))
    hass.states.async_set("binary_sensor.gate_closed", opened)
    await settle(hass, entry, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.calls == []
    hass.states.async_set("binary_sensor.gate_closed", closed)
    await settle(hass, entry, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert len(world.called("mammotion.start_mow")) == 1


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
async def test_an_unreadable_gate_counts_as_open(hass, freezer, state):
    world, entry = await _awaiting(hass, freezer)
    hass.states.async_set("binary_sensor.gate_closed", state)
    await settle(hass, entry, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.calls == []


# ---- active_group: stamped only on a verified start, reconciled at every exit -----------

async def test_a_refused_or_failed_start_stamps_no_group(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.react("mammotion.start_mow", lambda w, _d: w.set_mode(c.MODE_WORKING))  # no route
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.ERROR
    assert entry.runtime_data.store.session.active_group == ""


@pytest.mark.parametrize("held", [False, True])
async def test_exits_reconcile_active_group_to_the_hardware(hass, freezer, held):
    world, entry = await build(hass, freezer)
    if held:
        world.hold_docked("Back", battery=80)
    put(entry, session__active_group="A")
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    assert entry.runtime_data.store.session.active_group == ("B" if held else "")
    put(entry, session__active_group="A")
    await dispatch(hass, entry, "clear_error", freezer=freezer)
    assert entry.runtime_data.store.session.active_group == ("B" if held else "")


# ---- task areas: liveness, not existence --------------------------------------------------

async def test_dead_leftover_task_areas_do_not_hide_the_held_group(hass, freezer):
    world, entry = await build(hass, freezer)
    world.add_task_area("Back")
    world.add_task_area("Side", "unavailable")          # the previous job's leftover
    world.add_task_area("Front", "unavailable")
    assert entry.runtime_data.orchestrator.held_group() == "B"
    hass.states.async_set(world.task_areas[world.zone_hash("Side")], "MOWING")
    assert entry.runtime_data.orchestrator.held_group() == ""   # a mixed job is no group


async def test_a_half_planned_route_does_not_verify(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    def _half(w, _d):
        w.start_job_for("Front")                        # Group A is Front + Side
        w.set_charging(False)
        w.set_mode(c.MODE_WORKING)
    world.react("mammotion.start_mow", _half)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.ERROR


# ---- calendar titles -------------------------------------------------------------------------

async def test_an_ungrouped_completion_names_the_real_work_area(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start=TODAY_10, session__work_area="Slope")
    world.add_task_area("Slope")
    await tick(hass, entry, freezer, later(hours=2))
    await dispatch(hass, entry, "log_cut", freezer=freezer)
    assert world.events[-1]["summary"].startswith("Mowing — Slope, ")
    assert entry.runtime_data.store.counters.cuts == {"A": 0, "B": 0}


@pytest.mark.parametrize("work_area", ["", "Not working", "path"])
async def test_junk_work_areas_become_manual(hass, freezer, work_area):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start=TODAY_10, session__work_area=work_area)
    await tick(hass, entry, freezer, later(hours=2))
    await dispatch(hass, entry, "log_cut", freezer=freezer)
    assert world.events[-1]["summary"].startswith("Mowing — Manual, ")


async def test_a_skip_with_no_group_has_no_dangling_label(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.SCHEDULED, day__scheduled_group="",
        day__evaluated_at="2026-09-29T08:45:00-07:00")
    await tick(hass, entry, freezer, later(hours=4, minutes=5))
    assert world.events[-1]["summary"] == "Mowing — Skipped"


async def test_error_on_a_mow_day_without_a_mow_is_no_mow_today(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    await tick(hass, entry, freezer, later(hours=4))
    assert fsm(entry) == F.IDLE
    assert world.events[-1]["summary"] == "Mowing — Group A, Skipped"
    assert world.notifications[-1]["title"].endswith("No Mow Today")


async def test_close_window_withdraws_the_prompt_on_a_lost_day(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    hass.states.async_set("binary_sensor.dry_a", "off")
    await tick(hass, entry, freezer, later(hours=4))
    clears = [n for n in world.notifications if n["message"] == "clear_notification"]
    assert clears and clears[-1]["data"]["tag"] == "mower_prompt"


# ---- overseed: only the held group's day ----------------------------------------------------

async def test_an_overseed_hold_leaves_the_other_groups_day_alone(hass, freezer):
    hass.states.async_set("binary_sensor.allowed_a", "off")
    world, entry = await build(hass, freezer, at=local(2026, 10, 1, 8, 40),  # Thursday: B
                               **{c.CONF_MOW_ALLOWED["A"]: "binary_sensor.allowed_a"})
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    assert entry.runtime_data.store.day.scheduled_group == "B"


# ---- best effort (review M3) ------------------------------------------------------------------

async def test_a_failing_notify_never_stops_an_intent(hass, freezer):
    world, entry = await build(hass, freezer)

    async def _boom(_call):
        raise RuntimeError("phone unreachable")
    hass.services.async_register("notify", "test_phone", _boom)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    assert entry.runtime_data.store.day.prompt_id


async def test_a_raising_dock_cannot_halt_the_stale_sweep(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start="2026-09-28T10:00:00-07:00")
    world.set_charging(False)
    hass.states.async_set(world.mower.roles[c.ROLE_ACTIVITY], c.MODE_WORKING)
    await settle(hass, entry, freezer)

    def _raise(_w, _d):
        raise RuntimeError("cloud timeout")
    world.react("lawn_mower.dock", _raise)
    await tick(hass, entry, freezer, later(minutes=5))
    assert [n for n, _ in world.calls] == ["lawn_mower.dock", "mammotion.cancel_job"]
    assert fsm(entry) == F.AWAITING


# ---- the queue fails loud (review L2) ---------------------------------------------------------

async def test_queue_overflow_raises_a_repair_issue(hass: HomeAssistant):
    async def _never(_intent):
        return None
    dispatcher = Dispatcher(hass, handler=_never)             # no worker: nothing drains
    assert all(dispatcher.dispatch("telemetry_sync") for _ in range(QUEUE_MAX))
    assert dispatcher.dispatch("log_cut") is False
    issue = ir.async_get(hass).async_get_issue(c.DOMAIN, ISSUE_OVERFLOW)
    assert issue is not None and issue.translation_placeholders == {"intent": "log_cut"}
