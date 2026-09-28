"""Adverse reasons, recovery of held jobs, start guards, and the remaining carried-over
invariants (see tests/TRACEABILITY.md)."""
from datetime import timedelta

import pytest
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.util import dt as dt_util

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from .world import build, dispatch, fire_action, fsm, later, local, put, restart, settle, tick

REST_DAY = (2026, 9, 30, 8, 40)             # Wednesday: no group at 1x. A tuple: local() must
                                             # run at test time, after the test time zone is set.


async def _awaiting(hass, freezer, **kw):
    world, entry = await build(hass, freezer, **kw)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    return world, entry


def _held(world, entry, *, state=F.PAUSED, docked=True):
    """Yesterday's Group A job, still held by the mower."""
    if docked:
        world.hold_docked("Front", "Side", battery=60)
    else:
        world.start_job_for("Front", "Side")
        world.set_charging(False)
        world.set_mode(c.MODE_PAUSE)
    put(entry, state=state, session__start="2026-09-29T14:00:00-07:00")


# ---- adverse: the reason ladder, holds, self-guards --------------------------------------

async def test_adverse_reason_ladder(hass, freezer):
    _world, entry = await build(hass, freezer)
    reason = entry.runtime_data.orchestrator.adverse_reason
    now = dt_util.now()
    hass.states.async_set("sensor.lightning_distance", "3")
    hass.states.async_set("sensor.lightning_strike", (now - timedelta(minutes=1)).isoformat())
    assert reason() == "Lightning within 5"
    # a close strike an hour ago is not lightning: this abort is for heat (review L5)
    hass.states.async_set("sensor.lightning_strike", (now - timedelta(hours=1)).isoformat())
    hass.states.async_set("sensor.canopy", "93")
    assert reason() == "Canopy heat > 90°F"
    hass.states.async_set("sensor.lightning_strike", "unavailable")      # unreadable: not lightning
    assert reason() == "Canopy heat > 90°F"
    hass.states.async_set("weather.home", "hail")                         # the ladder's order
    assert reason() == "Weather: hail"
    hass.states.async_set("sensor.precip_type", "rain")
    assert reason() == "Weather: rain"


async def test_adverse_blocks_auto_start_and_keeps_the_heartbeat(hass, freezer):
    world, entry = await build(hass, freezer)
    entry.runtime_data.async_update_settings(auto_start=True)
    world.rain()
    await tick(hass, entry, freezer, later(minutes=5))
    assert world.calls == [] and fsm(entry) == F.AWAITING
    assert entry.runtime_data.store.day.ack_deadline                     # armed before the hold
    world.rain(False)
    await tick(hass, entry, freezer, later(minutes=31))                  # the heartbeat
    assert [name for name, _ in world.calls] == ["mammotion.start_mow"]


async def test_adverse_abort_self_guards(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 27, 10, 0))
    world.mow_manually("Back")
    await dispatch(hass, entry, "adverse_abort", freezer=freezer)       # nothing is adverse
    assert world.calls == []


# ---- recovery (conditions_recovered) -------------------------------------------------------

async def test_recovery_holds_a_job_until_conditions_are_optimal(hass, freezer):
    world, entry = await build(hass, freezer, at=local(*REST_DAY))
    _held(world, entry)
    hass.states.async_set("binary_sensor.dry_a", "off")
    await tick(hass, entry, freezer, later(minutes=5))                   # the floor tick
    assert fsm(entry) == F.PAUSED                                        # held before any write
    assert world.notifications[-1]["title"].endswith("Job held")
    hass.states.async_set("binary_sensor.dry_a", "on")                    # optimal's edge
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.AWAITING


async def test_recovery_under_adverse_holds_in_awaiting_without_buttons(hass, freezer):
    world, entry = await build(hass, freezer, at=local(*REST_DAY),
                               **{c.CONF_LIGHTNING_RECENCY: 30})
    _held(world, entry)
    entry.runtime_data.async_update_settings(auto_start=True)
    hass.states.async_set("sensor.lightning_distance", "2")
    hass.states.async_set("sensor.lightning_strike", dt_util.now().isoformat())
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    assert world.calls == [] and world.prompts() == []
    assert "not safely right now" in world.notifications[-1]["message"]


@pytest.mark.parametrize("state", [F.ERROR, F.SKIPPED])
async def test_recovery_never_overrides_error_or_a_skip(hass, freezer, state):
    world, entry = await build(hass, freezer, at=local(*REST_DAY))
    _held(world, entry, state=state)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == state and world.prompts() == []


async def test_recovery_floors_at_the_scheduler_time_and_the_season(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 30, 7, 0))
    _held(world, entry)
    await dispatch(hass, entry, "conditions_recovered", freezer=freezer)
    assert fsm(entry) == F.PAUSED
    hass.states.async_set("input_boolean.season", "off")
    await tick(hass, entry, freezer, later(hours=1, minutes=45))         # 08:45, out of season
    assert fsm(entry) == F.PAUSED


@pytest.mark.parametrize("docked", [True, False], ids=["docked", "on_the_lawn"])
@pytest.mark.parametrize("stamp", ["A", ""], ids=["stamped", "blank_stamp"])
async def test_a_held_job_resumes_in_place(hass, freezer, docked, stamp):
    world, entry = await build(hass, freezer, at=local(*REST_DAY))
    _held(world, entry, docked=docked)
    put(entry, day__scheduled_group=stamp)
    await tick(hass, entry, freezer, later(minutes=5))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_RESUME), freezer)
    assert [name for name, _ in world.calls] == ["lawn_mower.start_mowing"]
    assert entry.runtime_data.store.session.active_group == "A"         # the held group


async def test_an_exhausted_resume_names_the_remedy(hass, freezer):
    world, entry = await build(hass, freezer, at=local(*REST_DAY))
    _held(world, entry)
    world.ignore("lawn_mower.start_mowing", times=3)
    await tick(hass, entry, freezer, later(minutes=5))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_RESUME), freezer)
    assert fsm(entry) == F.ERROR
    assert "cancel it in the Mammotion app" in world.notifications[-1]["message"]


# ---- start_mow guards ------------------------------------------------------------------------

async def test_a_fresh_start_without_a_group_refuses_before_starting(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    put(entry, day__scheduled_group="")
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.calls == []
    assert fsm(entry) == F.ERROR
    assert entry.runtime_data.store.fsm.error_from == F.AWAITING       # never reached Starting
    assert "no zone group stamped" in world.notifications[-1]["message"]


async def test_duplicate_and_stale_dispatches_are_ignored(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    prompts = len(world.prompts())
    await dispatch(hass, entry, "start_mow", "prompt_user", freezer=freezer)
    assert fsm(entry) == F.RUNNING
    assert len(world.called("mammotion.start_mow")) == 1 and len(world.prompts()) == prompts
    assert "enter_error" not in entry.runtime_data.dispatcher.handled


async def test_the_group_is_stamped_before_scheduled_is_visible(hass, freezer):
    _world, entry = await build(hass, freezer)
    seen = []

    def _on_state(event):
        new = event.data["new_state"]
        if event.data["entity_id"] == c.STATE_ENTITY_ID and new and new.state == F.SCHEDULED:
            seen.append(new.attributes.get("scheduled_group"))

    hass.bus.async_listen("state_changed", _on_state)
    await tick(hass, entry, freezer, later(minutes=5))
    assert seen and seen[0] == "A"


async def test_previous_leftovers_do_not_verify_a_phantom_start(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.add_task_area("Front", "unavailable")                          # the last job's leftovers
    world.add_task_area("Side", "unavailable")
    world.react("mammotion.start_mow", lambda w, _d: w.set_mode(c.MODE_WORKING))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.ERROR


async def test_a_group_whose_own_sensors_are_dead_is_not_held(hass, freezer):
    world, entry = await build(hass, freezer)
    world.add_task_area("Back", "unavailable")
    assert entry.runtime_data.orchestrator.held_group() == ""


# ---- close_window / reboot / readiness -------------------------------------------------------

async def test_close_window_leaves_an_unadopted_live_run_alone(hass, freezer):
    """Defect 26: an Error the heal rule won't lift, with the owner's run out on the lawn."""
    world, entry = await _awaiting(hass, freezer)                      # past 08:45
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    world.mow_manually("Back")
    await tick(hass, entry, freezer, later(hours=4))                     # window close
    assert fsm(entry) == F.ERROR
    assert not any(n.get("title", "").endswith("No Mow Today") for n in world.notifications)
    assert world.events == []


async def test_a_reboot_after_the_job_finished_completes_it(hass, freezer):
    _world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start="2026-09-29T08:00:00-07:00")
    await restart(hass, entry, freezer)                                  # the mower is READY, docked
    assert fsm(entry) == F.IDLE
    assert "telemetry_idle" in entry.runtime_data.dispatcher.handled


async def test_readiness_refreshes_a_stale_camera_after_sunrise(hass, freezer):
    world, entry = await build(hass, freezer)
    refreshed = []

    async def _update(call):
        refreshed.append(call.data["entity_id"])
        hass.states.async_set(world.mower.roles[c.ROLE_CAMERA], "Light")

    hass.services.async_register("homeassistant", "update_entity", _update)
    hass.states.async_set(world.mower.roles[c.ROLE_CAMERA], "Dark")
    await dispatch(hass, entry, "evaluate_readiness", freezer=freezer)
    assert refreshed and world.mower.roles[c.ROLE_CAMERA] in refreshed[0]
    assert hass.states.get("binary_sensor.luba_ready").state == "on"


async def test_every_intent_has_a_handler(hass, freezer):
    _world, entry = await build(hass, freezer)
    orchestrator = entry.runtime_data.orchestrator
    assert set(orchestrator._handlers) == set(orchestrator.INTENTS)


async def test_rotation_logs_a_drifted_setting(hass, freezer):
    _world, entry = await build(hass, freezer, at=local(2026, 9, 28, 0, 59))
    lines = []
    hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, lambda e: lines.append(e.data["message"]))
    put(entry, settings__angle_1=99)
    await tick(hass, entry, freezer, later(minutes=1))
    assert any("unknown current value (a1=99)" in line for line in lines)
    assert entry.runtime_data.angle_1 == 48          # 99 shows as the first entry; one step on


@pytest.mark.parametrize(("allowed", "day", "held"), [
    ({"A": "on"}, (2026, 9, 29, 8, 40), False),           # Tuesday A: the authority says mow
    ({"B": "off"}, (2026, 10, 1, 8, 40), True),           # Thursday B: B's authority holds
])
async def test_the_overseed_authority_is_read_per_group(hass, freezer, allowed, day, held):
    opts = {}
    for group, state in allowed.items():
        entity_id = f"binary_sensor.allowed_{group.lower()}"
        hass.states.async_set(entity_id, state)
        opts[c.CONF_MOW_ALLOWED[group]] = entity_id
    _world, entry = await build(hass, freezer, at=local(*day), **opts)
    await tick(hass, entry, freezer, later(minutes=5))
    assert (fsm(entry) == F.IDLE) is held
