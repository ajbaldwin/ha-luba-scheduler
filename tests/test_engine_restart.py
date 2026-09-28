"""A restart is not a session boundary (YAML v3.1.25): nothing is lost mid-session,
mid-abort or mid-prompt, and a restart spanning the scheduler time keeps the day (M4)."""
from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from .world import build, fire_action, fsm, later, local, put, restart, settle, tick


async def _running(hass, freezer):
    world, entry = await build(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert fsm(entry) == F.RUNNING
    return world, entry


async def test_restart_mid_session_loses_nothing(hass, freezer):
    world, entry = await _running(hass, freezer)
    before = entry.runtime_data.store.session
    start, group = before.start, before.active_group
    await tick(hass, entry, freezer, later(minutes=30))
    await restart(hass, entry, freezer, downtime=later(minutes=2))
    co = entry.runtime_data
    assert fsm(entry) == F.RUNNING
    assert (co.store.session.start, co.store.session.active_group) == (start, group)
    assert "reboot_recover" in co.dispatcher.handled
    await tick(hass, entry, freezer, later(minutes=30))
    world.finish()
    await tick(hass, entry, freezer, later(minutes=3))
    assert fsm(entry) == F.IDLE
    assert co.store.counters.cuts["A"] == 1
    assert world.events[-1]["summary"].startswith("Mowing — Group A, 6")   # ~62 min, across it


async def test_restart_mid_abort_keeps_the_reason_and_resumes(hass, freezer):
    world, entry = await _running(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=20))
    world.rain()
    await settle(hass, entry, freezer)
    assert [name for name, _ in world.calls][-1] == "lawn_mower.dock"
    assert fsm(entry) == F.RETURNING
    world.hold_docked(battery=50)                                  # docked, job held
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.PAUSED
    reason = entry.runtime_data.store.session.abort_reason
    assert reason == "Weather: rain"

    await restart(hass, entry, freezer, downtime=later(minutes=10))
    co = entry.runtime_data
    assert fsm(entry) == F.PAUSED
    assert co.store.session.abort_reason == reason
    world.rain(False)
    world.set_battery(100)                                         # ready edge → recovery
    await settle(hass, entry, freezer)
    assert fsm(entry) == F.AWAITING
    assert "Weather abort (Weather: rain) is over" in world.prompts()[-1]["message"]
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_RESUME), freezer)
    assert [name for name, _ in world.calls][-1] == "lawn_mower.start_mowing"
    assert fsm(entry) == F.RUNNING
    assert co.store.session.abort_reason == ""


async def test_restart_mid_prompt_keeps_the_prompt_live(hass, freezer):
    world, entry = await build(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    action = world.last_prompt_action(c.ACT_START)
    await restart(hass, entry, freezer, downtime=later(minutes=5))
    assert fsm(entry) == F.AWAITING
    assert entry.runtime_data.store.day.ack_deadline
    await fire_action(hass, entry, action, freezer)               # the pre-restart tap works
    assert len(world.called("mammotion.start_mow")) == 1
    assert fsm(entry) == F.RUNNING


async def test_ack_deadline_passed_during_downtime_reprompts_once(hass, freezer):
    world, entry = await build(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    assert len(world.prompts()) == 1
    await restart(hass, entry, freezer, downtime=later(minutes=45))
    assert fsm(entry) == F.AWAITING
    assert entry.runtime_data.dispatcher.handled.count("reprompt") == 1
    assert len(world.prompts()) == 2


async def test_restart_spanning_the_scheduler_time_keeps_the_day(hass, freezer):
    """Review M4: HA down across 08:45 → reboot_recover runs schedule_day once."""
    world, entry = await build(hass, freezer, at=local(2026, 9, 29, 8, 30))
    await restart(hass, entry, freezer, downtime=later(minutes=30))
    assert fsm(entry) == F.AWAITING
    assert entry.runtime_data.dispatcher.handled.count("schedule_day") == 1
    assert len(world.prompts()) == 1
    await restart(hass, entry, freezer, downtime=later(minutes=1))   # again: no second run
    assert entry.runtime_data.dispatcher.handled.count("schedule_day") == 0
    assert len(world.prompts()) == 1


async def test_restart_while_starting_is_an_error(hass, freezer):
    world, entry = await build(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    put(entry, state=F.STARTING)
    await restart(hass, entry, freezer)
    assert fsm(entry) == F.ERROR
    assert "start presumed lost" in world.notifications[-1]["message"]
