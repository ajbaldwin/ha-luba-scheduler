"""After sunset the window close is tomorrow's (sun.sun's next_setting rolls over).
Nothing may read that as "still before today's cutoff" (live 2026-09-27 21:13)."""
from datetime import timedelta

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from .world import build, dispatch, fsm, local, put, restart, settle


def _night(hass, day: tuple[int, int, int]) -> None:
    """21:00, the sun down; next_setting and next_dusk are tomorrow's."""
    tomorrow = local(*day) + timedelta(days=1)
    hass.states.async_set("sun.sun", "below_horizon", {
        "next_setting": tomorrow.replace(hour=18, minute=30).isoformat(),
        "next_dusk": tomorrow.replace(hour=18, minute=58).isoformat()})


async def test_a_restart_after_sunset_on_a_mow_day_does_not_schedule_it(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 29, 21, 0))   # Tuesday: Group A
    _night(hass, (2026, 9, 29))
    await restart(hass, entry, freezer)
    assert "schedule_day" not in entry.runtime_data.dispatcher.handled
    assert fsm(entry) == F.IDLE and world.notifications == []


async def test_a_load_before_the_cutoff_still_recovers_the_day(hass, freezer):
    """The M4 case keeps working when the close is today's: loaded at 11:00, the
    missed 08:45 schedule runs once."""
    _world, entry = await build(hass, freezer, at=local(2026, 9, 29, 11, 0))
    assert entry.runtime_data.dispatcher.handled.count("schedule_day") == 1
    assert fsm(entry) == F.AWAITING


async def test_a_ready_edge_after_sunset_does_not_offer_a_held_job(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 30, 21, 0))   # Wednesday
    _night(hass, (2026, 9, 30))
    world.hold_docked("Front", "Side", battery=60)
    put(entry, state=F.PAUSED, session__start="2026-09-30T14:00:00-07:00")
    await settle(hass, entry, freezer)
    world.set_battery(100)                                                      # ready edge
    await dispatch(hass, entry, "conditions_recovered", freezer=freezer)
    assert fsm(entry) == F.PAUSED
    assert world.notifications == [] and world.prompts() == []
    assert c.MODE_PAUSE == world.mode
