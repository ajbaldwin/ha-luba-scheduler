"""The 08:45 race (handoff §3, defect 16): schedule_day and conditions_recovered(floor)
land at the same instant. Whichever runs first: exactly one prompt and one start."""
import pytest

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from .world import build, dispatch, fire_action, fsm, jump, later, local, put, tick

FLOOR = ("conditions_recovered", {"trigger_source": "floor"})
ORDERS = {"schedule_first": ["schedule_day", FLOOR], "recovery_first": [FLOOR, "schedule_day"]}


async def _at_845(hass, freezer, *, held: bool, auto: bool):
    # Built just before 08:45 (at 08:45 itself, reboot_recover would already run
    # the missed schedule — review M4); then the clock moves to 08:45 without
    # firing the time trigger, so the test enqueues the two intents itself.
    world, entry = await build(hass, freezer, at=local(2026, 9, 29, 8, 44))
    entry.runtime_data.async_update_settings(auto_start=auto)
    if held:                     # yesterday's group A job, docked, held, fully charged
        world.hold_docked("Front", "Side", battery=100)
        put(entry, state=F.PAUSED, session__start="2026-09-28T14:00:00-07:00",
            session__active_group="A", day__scheduled_group="A",
            day__evaluated_at="2026-09-28T08:45:00-07:00")
    jump(freezer, later(minutes=1))
    return world, entry


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("held", [False, True], ids=["fresh_day", "held_job"])
async def test_one_prompt_whichever_runs_first(hass, freezer, order, held):
    world, entry = await _at_845(hass, freezer, held=held, auto=False)
    await dispatch(hass, entry, *ORDERS[order], freezer=freezer)
    assert fsm(entry) == F.AWAITING
    assert len(world.prompts()) == 1
    # and the one prompt starts exactly one job
    prefix = c.ACT_RESUME if held and order == "recovery_first" else c.ACT_START
    await fire_action(hass, entry, world.last_prompt_action(prefix), freezer)
    service = "lawn_mower.start_mowing" if held else "mammotion.start_mow"
    assert [name for name, _ in world.calls] == [service]
    assert fsm(entry) == F.RUNNING


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("held", [False, True], ids=["fresh_day", "held_job"])
async def test_one_auto_start_whichever_runs_first(hass, freezer, order, held):
    world, entry = await _at_845(hass, freezer, held=held, auto=True)
    await dispatch(hass, entry, *ORDERS[order], freezer=freezer)
    service = "lawn_mower.start_mowing" if held else "mammotion.start_mow"
    assert [name for name, _ in world.calls] == [service]
    assert fsm(entry) == F.RUNNING


async def test_the_real_time_trigger_fires_both_in_order(hass, freezer):
    world, entry = await build(hass, freezer, at=local(2026, 9, 29, 8, 44, 30))
    await tick(hass, entry, freezer, later(minutes=0.5))
    handled = entry.runtime_data.dispatcher.handled
    assert handled.index("schedule_day") < handled.index("conditions_recovered")
    assert len(world.prompts()) == 1


async def test_carryover_resumes_the_held_group_and_credits_it(hass, freezer):
    """Thursday's group B job still held on Tuesday (A's day): the start resumes B,
    says so, and the cut is credited to B, the group actually mowed (defect 28)."""
    world, entry = await _at_845(hass, freezer, held=False, auto=False)
    world.hold_docked("Back", battery=100)
    put(entry, state=F.PAUSED, session__start="2026-09-24T14:00:00-07:00",
        day__scheduled_group="B", day__evaluated_at="2026-09-24T08:45:00-07:00")
    await dispatch(hass, entry, "schedule_day", FLOOR, freezer=freezer)
    assert entry.runtime_data.store.day.scheduled_group == "A"
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert [name for name, _ in world.calls] == ["lawn_mower.start_mowing"]
    assert any("Group B carried over" in n.get("title", "") for n in world.notifications)
    assert entry.runtime_data.store.session.active_group == "B"
    await tick(hass, entry, freezer, later(minutes=40))
    world.finish()
    await tick(hass, entry, freezer, later(minutes=3))
    assert entry.runtime_data.store.counters.cuts == {"A": 0, "B": 1}
