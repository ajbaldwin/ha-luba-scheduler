"""Replay tests: real days, and what the port does with them (design Q9).

09-17 is from the recorder; the August days are reconstructed from the defect
log (see tests/replay/days.py). Each asserts the FSM path and the outcomes,
and names where the port deliberately differs from what the YAML did.
"""
from dataclasses import replace

from homeassistant.helpers import issue_registry as ir

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F
from custom_components.luba.health import ISSUE_DEAD

from .replay.days import DAY_0801, DAY_0813, DAY_0821, DAY_0822, DAY_0917, YAML_0917
from .replay.runner import S, replay, within


def _titles(run) -> list[str]:
    return [n.get("title", "") for n in run.world.notifications]


async def test_0917_follows_the_yaml_path_and_logs_what_it_lost(hass, freezer):
    run = await replay(hass, freezer, DAY_0917)
    assert run.path == [(frm, to) for _, frm, to in YAML_0917]
    for (t, frm, to), (yaml_t, _, _) in zip(run.transitions, YAML_0917, strict=True):
        assert within(t, yaml_t, 5), (frm, to, t, yaml_t)
    # M7: the YAML logged and counted nothing that day. The port logs both jobs
    # and counts the Group B cut; the ungrouped zone's job is logged, not counted.
    assert [e["summary"] for e in run.world.events] == ["Mowing — Group B", "Mowing — Manual"]
    assert run.store.counters.cuts == {"A": 0, "B": 1}
    assert run.store.counters.last_logged_cut == "Manual/unknown|2026-09-17"
    assert run.world.calls == []                          # the owner ran the mower, not Luba
    assert run.world.prompts() == []                      # optimal never turned on
    assert "enter_error" not in run.entry.runtime_data.dispatcher.handled


async def test_0801_heat_abort_then_unattended_resume(hass, freezer):
    run = await replay(hass, freezer, DAY_0801)
    assert run.path == [
        (F.SCHEDULED, F.RUNNING),                          # the app run, adopted
        (F.RUNNING, F.RETURNING), (F.RETURNING, F.PAUSED),  # heat abort, docked holding
        (F.PAUSED, F.AWAITING),                            # optimal's edge → Resume prompt
        (F.AWAITING, F.STARTING), (F.STARTING, F.RUNNING),
        (F.RUNNING, F.COMPLETED), (F.COMPLETED, F.IDLE)]
    calls = [name for name, _ in run.world.calls]
    assert calls == ["lawn_mower.dock"] + ["lawn_mower.start_mowing"] * 3   # 2 ignored
    assert "mammotion.start_mow" not in calls                           # defect 12
    abort = next(n for n in run.world.notifications if n.get("title") == "Mowing Aborted!")
    assert abort["message"].startswith("Canopy heat > 90°F")
    resume = run.world.prompts()[-1]
    assert "Weather abort (Canopy heat > 90°F) is over" in resume["message"]
    assert run.store.session.abort_reason == ""                          # cleared on verify
    assert run.store.counters.cuts["A"] == 1
    assert run.world.events[-1]["summary"].startswith("Mowing — Group A, ")


async def test_0813_docked_heat_abort_resumes_at_the_resume_floor(hass, freezer):
    run = await replay(hass, freezer, DAY_0813)
    assert F.ERROR not in {to for _, to in run.path}       # the YAML stranded in Error here
    assert [name for name, _ in run.world.calls] == [
        "mammotion.start_mow", "lawn_mower.dock", "lawn_mower.start_mowing"]
    assert run.path[-2:] == [(F.RUNNING, F.COMPLETED), (F.COMPLETED, F.IDLE)]
    assert len(run.world.events) == 1                      # logged (the YAML's was lost)
    assert run.world.events[0]["summary"].startswith("Mowing — Group B, ")
    assert run.store.counters.cuts == {"A": 0, "B": 1}


async def test_0821_carryover_resumes_past_a_rebuilt_zone_and_counts_the_held_group(hass, freezer):
    run = await replay(hass, freezer, DAY_0821)
    assert ir.async_get(hass).async_get_issue(c.DOMAIN, ISSUE_DEAD) is not None
    assert run.store.day.scheduled_group == "B"
    assert [name for name, _ in run.world.calls] == ["lawn_mower.start_mowing"]  # no areas
    assert "Test Mower — Group A carried over" in _titles(run)
    assert F.ERROR not in {to for _, to in run.path}       # the YAML errored on B's dead switch
    assert run.store.counters.cuts == {"A": 1, "B": 0}    # defect 28: the group mowed
    assert run.world.events[-1]["summary"].startswith("Mowing — Group A, ")


async def test_0822_reboot_with_a_slow_mammotion_leaves_a_resting_fsm_alone(hass, freezer):
    run = await replay(hass, freezer, DAY_0822)
    assert run.path == [(F.IDLE, F.RUNNING), (F.RUNNING, F.COMPLETED), (F.COMPLETED, F.IDLE)]
    assert not any(t.endswith("No Mow Today") or t.endswith("Error") for t in _titles(run))
    assert [e["summary"] for e in run.world.events] == ["Mowing — Group B"]
    assert run.store.counters.cuts["B"] == 1


async def test_0822_an_error_at_close_after_a_mow_is_swept_silently(hass, freezer):
    """v3.1.42: even if the day ends in Error, a day that mowed is not "No Mow Today"."""
    day = replace(DAY_0822, steps=[*DAY_0822.steps,
                                   S("13:10:20", "dispatch", "enter_error",
                                     {"error_context": "reboot: dependencies not ready"})])
    run = await replay(hass, freezer, day)
    assert run.path[-2:] == [(F.IDLE, F.ERROR), (F.ERROR, F.IDLE)]
    assert not any(t.endswith("No Mow Today") for t in _titles(run))
    assert [e["summary"] for e in run.world.events] == ["Mowing — Group B"]
