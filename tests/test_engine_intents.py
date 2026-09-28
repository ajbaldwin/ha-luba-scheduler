"""Branch coverage for each intent, against the fake world (active mode)."""
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import EVENT_LOGBOOK_ENTRY

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from .world import build, dispatch, fire_action, fsm, later, local, put, settle, tick

YESTERDAY = "2026-09-28T10:00:00-07:00"


async def _awaiting(hass, freezer, **kw):
    world, entry = await build(hass, freezer, **kw)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    return world, entry


async def _running(hass, freezer, **kw):
    world, entry = await _awaiting(hass, freezer, **kw)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.RUNNING
    return world, entry


# ---- schedule_day -------------------------------------------------------------------

async def test_overseed_hold_skips_the_day_once(hass, freezer):
    hass.states.async_set("binary_sensor.allowed_a", "off")
    world, entry = await build(hass, freezer, **{c.CONF_MOW_ALLOWED["A"]: "binary_sensor.allowed_a"})
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.IDLE
    assert [e["summary"] for e in world.events] == ["Mowing — Group A, Skipped (overseed)"]
    assert world.prompts() == []
    await dispatch(hass, entry, "schedule_day", freezer=freezer)       # a re-run: no duplicate
    assert len(world.events) == 1


async def test_unavailable_overseed_authority_holds(hass, freezer):
    hass.states.async_set("binary_sensor.allowed_a", "unavailable")
    world, entry = await build(hass, freezer, **{c.CONF_MOW_ALLOWED["A"]: "binary_sensor.allowed_a"})
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.IDLE and world.prompts() == []


async def test_out_of_season_and_rest_days_do_nothing(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 27, 8, 40))  # a Sunday
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.IDLE and world.notifications == []
    hass.states.async_set("input_boolean.season", "off")
    await dispatch(hass, entry, "schedule_day", freezer=freezer)
    assert fsm(entry) == F.IDLE


async def test_stale_carryover_is_swept_then_the_day_scheduled(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start=YESTERDAY, session__active_group="A")
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    assert any(n.get("title", "").endswith("Session Cleaned Up") for n in world.notifications)
    assert entry.runtime_data.store.session.start == ""


async def test_stale_working_job_is_cancelled_before_scheduling(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start=YESTERDAY)
    world.ignore("lawn_mower.dock")
    world.set_charging(False)
    hass.states.async_set(world.mower.roles[c.ROLE_ACTIVITY], c.MODE_WORKING)
    await settle(hass, entry, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    assert [n for n, _ in world.calls] == ["lawn_mower.dock", "mammotion.cancel_job"]
    assert fsm(entry) == F.AWAITING


async def test_uncancellable_stale_job_is_an_error(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start=YESTERDAY)
    world.ignore("lawn_mower.dock")
    world.ignore("mammotion.cancel_job")
    hass.states.async_set(world.mower.roles[c.ROLE_ACTIVITY], c.MODE_WORKING)
    await settle(hass, entry, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.ERROR
    assert "could not cancel" in world.notifications[-1]["message"]


# ---- prompt / reprompt / snooze -------------------------------------------------------

async def test_not_ready_waits_in_scheduled_then_prompts_on_the_edge(hass, freezer):
    world, entry = await build(hass, freezer)
    world.set_battery(80)                                           # below the fresh floor
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.SCHEDULED
    assert world.prompts() == []
    world.set_battery(100)                                          # ready edge
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.AWAITING and len(world.prompts()) == 1


async def test_snooze_rearms_the_deadline_and_reprompts_later(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    first = entry.runtime_data.store.day.ack_deadline
    await tick(hass, entry, freezer, later(minutes=10))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_SNOOZE), freezer)
    assert entry.runtime_data.store.day.ack_deadline > first
    await tick(hass, entry, freezer, later(minutes=25))            # the old deadline passes
    assert len(world.prompts()) == 1
    await tick(hass, entry, freezer, later(minutes=6))             # the snoozed one fires
    assert len(world.prompts()) == 2
    assert entry.runtime_data.dispatcher.handled.count("reprompt") == 1


async def test_reprompt_with_conditions_lapsed_returns_to_scheduled(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    hass.states.async_set("binary_sensor.dry_a", "off")
    await tick(hass, entry, freezer, later(minutes=31))
    assert fsm(entry) == F.SCHEDULED
    assert world.notifications[-1]["message"].startswith("Conditions paused the mow")


async def test_adverse_prompt_holds_without_buttons(hass, freezer):
    world, entry = await build(hass, freezer)
    world.rain()
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    assert world.prompts() == []
    assert "not safe right now" in world.notifications[-1]["message"]


# ---- start_mow --------------------------------------------------------------------------

async def test_route_never_planned_is_an_error(hass, freezer):
    """Defect 23: MODE_WORKING on a stale breakpoint — the job's task areas never appear."""
    world, entry = await _awaiting(hass, freezer)
    world.react("mammotion.start_mow", lambda w, _d: w.set_mode(c.MODE_WORKING))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.ERROR
    assert "no route was planned" in world.notifications[-1]["message"]


async def test_late_start_heals_error_to_running(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.ignore("mammotion.start_mow", times=3)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.ERROR
    assert entry.runtime_data.store.fsm.error_from == F.STARTING
    world.start_job_for("Front", "Side")
    world.set_mode(c.MODE_WORKING)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.RUNNING
    assert entry.runtime_data.store.session.active_group == "A"


async def test_working_in_error_from_elsewhere_does_not_heal(hass, freezer):
    world, entry = await build(hass, freezer)
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    world.set_mode(c.MODE_WORKING)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.ERROR


async def test_resume_uses_the_lower_floor(hass, freezer):
    """A held job resumes at the resume floor (20%) on a day schedule_day leaves alone.

    On a mow day schedule_day writes Scheduled over the held job and prompt_user
    then waits for the fresh-start readiness floor — faithful to the YAML."""
    world, entry = await build(hass, freezer, at=local(2026, 9, 30, 8, 40))  # Wednesday
    world.hold_docked("Front", "Side", battery=30)
    put(entry, state=F.PAUSED, session__start=YESTERDAY, day__scheduled_group="A")
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.AWAITING
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_RESUME), freezer)
    assert [n for n, _ in world.calls] == ["lawn_mower.start_mowing"]


async def test_fresh_start_below_the_floor_is_refused(hass, freezer):
    world, entry = await _awaiting(hass, freezer)
    world.set_battery(90)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.calls == [] and fsm(entry) == F.ERROR


# ---- telemetry ---------------------------------------------------------------------------

async def test_offline_then_back_at_the_dock(hass, freezer):
    world, entry = await _running(hass, freezer)
    world.set_mode("unavailable")
    await tick(hass, entry, freezer, later(minutes=6))
    assert fsm(entry) == F.OFFLINE
    assert entry.runtime_data.store.fsm.prior_state == F.RUNNING
    assert world.notifications[-1]["title"].endswith("Offline")
    world.set_mode(c.MODE_READY)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.IDLE


async def test_offline_inside_the_startup_grace_is_ignored(hass, freezer):
    world, entry = await build(hass, freezer)
    put(entry, state=F.RUNNING, session__start=YESTERDAY)
    world.set_mode("unavailable")
    await tick(hass, entry, freezer, later(minutes=4.5))
    assert fsm(entry) == F.RUNNING


async def test_mode_charging_is_logged_not_acted_on(hass, freezer):
    world, entry = await _running(hass, freezer)
    lines = []
    hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, lambda e: lines.append(e.data["message"]))
    world.set_mode(c.MODE_CHARGING)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.RUNNING
    assert any("MODE_CHARGING observed" in line for line in lines)


async def test_adopted_manual_run_is_stamped_counted_and_logged(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 27, 10, 0))    # Sunday
    world.mow_manually("Back")
    await settle(hass, entry, freezer)
    co = entry.runtime_data
    assert fsm(entry) == F.RUNNING
    assert co.store.day.scheduled_group == "B" and co.store.session.active_group == "B"
    await tick(hass, entry, freezer, later(minutes=30))
    world.finish()
    await tick(hass, entry, freezer, later(minutes=3))
    assert fsm(entry) == F.IDLE
    assert co.store.counters.cuts["B"] == 1
    assert world.events[-1]["summary"] == "Mowing — Group B"   # adopted: no session metrics


async def test_completion_is_logged_and_counted_once(hass, freezer):
    world, entry = await _running(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=60))
    world.set_progress(100)
    await settle(hass, entry, freezer)
    world.set_progress(0)
    world.set_progress(100)                                         # a second crossing, same day
    await settle(hass, entry, freezer)
    assert len(world.events) == 1
    assert entry.runtime_data.store.counters.cuts["A"] == 1


# ---- the window, dusk, weather -------------------------------------------------------------

async def test_close_window_with_no_mow_logs_skipped(hass, freezer):
    world, entry = await build(hass, freezer)
    world.set_battery(80)
    await tick(hass, entry, freezer, later(minutes=5))
    assert fsm(entry) == F.SCHEDULED
    await tick(hass, entry, freezer, later(hours=4))               # window close 12:40
    assert fsm(entry) == F.IDLE
    assert world.events[-1]["summary"] == "Mowing — Group A, Skipped"
    assert world.notifications[-1]["title"].endswith("No Mow Today")


async def test_close_window_leaves_a_running_mow_alone(hass, freezer):
    world, entry = await _running(hass, freezer)
    await tick(hass, entry, freezer, later(hours=3, minutes=56))
    assert fsm(entry) == F.RUNNING and world.events == []


async def test_close_window_finalises_a_weather_aborted_docked_job(hass, freezer):
    world, entry = await _running(hass, freezer)
    world.rain()
    await settle(hass, entry, freezer)
    world.hold_docked(battery=50)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.PAUSED
    await tick(hass, entry, freezer, later(hours=4))
    assert fsm(entry) == F.IDLE
    assert world.events[-1]["summary"] == "Mowing — Group A, Skipped (Weather: rain)"
    assert entry.runtime_data.store.session.abort_reason == ""
    assert entry.runtime_data.store.session.active_group == "A"   # still held on the mower


async def test_error_on_a_non_mow_day_is_swept_silently(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 27, 8, 40))  # Sunday
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    await tick(hass, entry, freezer, later(hours=4))
    assert fsm(entry) == F.IDLE and world.events == []


async def test_hard_stop_docks_a_mower_still_out_at_dusk(hass, freezer):
    world, entry = await _running(hass, freezer)
    await tick(hass, entry, freezer, later(hours=5, minutes=30))  # dusk 14:10
    assert [n for n, _ in world.calls][-1] == "lawn_mower.dock"
    assert entry.runtime_data.store.session.abort_reason == "Dusk hard stop"
    assert world.notifications[-1]["title"].endswith("Hard Stop at Dusk")


async def test_hard_stop_that_does_not_take_is_an_error(hass, freezer):
    world, entry = await _running(hass, freezer)
    world.ignore("lawn_mower.dock", times=5)
    await tick(hass, entry, freezer, later(hours=5, minutes=30))
    assert fsm(entry) == F.ERROR
    assert "stranded" in world.notifications[-1]["message"]


async def test_adverse_abort_on_a_manual_run_docks_without_bookkeeping(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 27, 10, 0))
    world.mow_manually("Front", "Side", "Back")                   # mixed: matches no group
    await settle(hass, entry, freezer)
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    world.rain()
    await settle(hass, entry, freezer)
    assert [n for n, _ in world.calls] == ["lawn_mower.dock"]
    assert "Manual session" in world.notifications[-1]["message"]
    assert entry.runtime_data.store.session.abort_reason == ""


async def test_adverse_tick_catches_a_run_started_into_danger(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 27, 10, 0))
    world.rain()
    await settle(hass, entry, freezer)
    world.mow_manually("Back")                                      # started in the rain
    await tick(hass, entry, freezer, later(minutes=5))
    assert [n for n, _ in world.calls] == ["lawn_mower.dock"]


# ---- errors, toggles, rotation, the gate alert ---------------------------------------------

async def test_clear_error_from_the_button_and_the_notification(hass, freezer):
    world, entry = await build(hass, freezer)
    await dispatch(hass, entry, ("enter_error", {"error_context": "x"}), freezer=freezer)
    assert world.notifications[-1]["data"]["actions"] == [
        {"action": c.ACT_CLEAR_ERROR, "title": "Clear Error"}]
    await hass.services.async_call("button", SERVICE_PRESS,
                                   {"entity_id": "button.luba_clear_error"}, blocking=True)
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.IDLE
    await dispatch(hass, entry, ("enter_error", {"error_context": "y"}), freezer=freezer)
    await fire_action(hass, entry, c.ACT_CLEAR_ERROR, freezer)
    assert fsm(entry) == F.IDLE
    await fire_action(hass, entry, c.ACT_CLEAR_ERROR, freezer)     # stale: ignored
    assert fsm(entry) == F.IDLE


async def test_nested_error_is_suppressed(hass, freezer):
    world, entry = await build(hass, freezer)
    await dispatch(hass, entry, ("enter_error", {"error_context": "first"}),
                   ("enter_error", {"error_context": "second"}), freezer=freezer)
    assert [n["message"] for n in world.notifications if n.get("title", "").endswith("Error")] \
        == ["first"]


async def test_toggle_auto_from_the_notification(hass, freezer):
    world, entry = await build(hass, freezer)
    await fire_action(hass, entry, c.ACT_TOGGLE_AUTO, freezer)
    assert entry.runtime_data.store.settings.auto_start is True
    assert hass.states.get("switch.luba_auto_start").state == "on"
    assert world.notifications[-1]["message"] == "Auto-start is now on."


async def test_monday_rotation_advances_and_resets(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 28, 0, 59))   # Monday
    co = entry.runtime_data
    co.store.counters.cuts = {"A": 2, "B": 1}
    await tick(hass, entry, freezer, later(minutes=1))
    s = co.store.settings
    assert (co.angle_1, co.spacing) == (48, 29)                     # second entries
    assert (s.cutting_height, s.cuts_per_group) == (70, 3)          # late September
    assert co.store.counters.cuts == {"A": 0, "B": 0}
    await tick(hass, entry, freezer, later(hours=24))               # Tuesday: no rotation
    assert co.angle_1 == 48


async def test_gate_zone_crossing_alert(hass, freezer):
    world, entry = await build(hass, freezer)
    world.set_work_area("Side")
    await settle(hass, entry, freezer)
    world.set_work_area("Back")
    await settle(hass, entry, freezer)
    assert world.notifications[-1]["title"].endswith("Close the Gate")
