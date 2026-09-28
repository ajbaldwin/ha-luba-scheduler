"""Whole-day scenarios against the fake world (active mode unless stated)."""
from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F
from custom_components.luba.mammotion import START_MOW_FIELDS

from .world import build, fire_action, fsm, later, settle, tick


async def test_happy_day_prompt_start_complete_log_count(hass, freezer):
    world, entry = await build(hass, freezer)
    co = entry.runtime_data
    assert fsm(entry) == F.IDLE

    await tick(hass, entry, freezer, later(minutes=5))           # 08:45 scheduler
    assert fsm(entry) == F.AWAITING
    assert co.store.day.scheduled_group == "A"
    assert len(world.prompts()) == 1

    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    starts = world.called("mammotion.start_mow")
    assert len(starts) == 1
    assert sorted(starts[0]["areas"]) == sorted([world.mower.zones["Front"],
                                                 world.mower.zones["Side"]])
    assert starts[0]["blade_height"] == co.store.settings.cutting_height
    assert starts[0]["toward_mode"] == 1
    assert START_MOW_FIELDS <= set(starts[0])                   # every field sent (defect 22)
    assert starts[0]["toward"] == int(hass.states.get("sensor.luba_next_mow_angle").state)
    assert fsm(entry) == F.RUNNING
    assert co.store.session.active_group == "A"
    assert co.store.session.start
    assert any(n["message"] == "clear_notification" and n["data"]["tag"] == "mower_prompt"
               for n in world.notifications)                  # the answered prompt is withdrawn

    await tick(hass, entry, freezer, later(minutes=90))
    assert "reprompt" in co.dispatcher.handled                # the 09:15 heartbeat fired…
    assert fsm(entry) == F.RUNNING and len(world.prompts()) == 1   # …and was ignored
    world.finish()
    await settle(hass, entry, freezer)
    await tick(hass, entry, freezer, later(minutes=3))           # idle reconcile
    assert fsm(entry) == F.IDLE
    assert co.store.counters.cuts == {"A": 1, "B": 0}
    assert len(world.events) == 1
    assert world.events[0]["summary"].startswith("Mowing — Group A, ")
    assert co.store.session.start == "" and co.store.session.active_group == ""
    assert "enter_error" not in co.dispatcher.handled
    assert "adverse_abort" not in co.dispatcher.handled       # the /5 tick only fires when adverse
