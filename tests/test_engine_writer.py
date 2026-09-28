"""The FSM writer contract: one logbook line per transition (with corr), and a refused
write stops its handler cold — no downstream side effects (review M2)."""
import pytest
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import callback

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F
from custom_components.luba.fsm_writer import FsmWriter, TransitionRefused

from .world import build, dispatch, fire_action, fsm, later, settle, tick


async def test_every_state_change_has_exactly_one_logbook_line(hass, freezer):
    world, entry = await build(hass, freezer)
    lines, states = [], []

    @callback
    def _log(event):
        if event.data.get("name", "").endswith("FSM"):
            lines.append(event.data["message"])

    @callback
    def _state(event):
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new and old and new.state != old.state:
            states.append((old.state, new.state))

    hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, _log)
    hass.bus.async_listen("state_changed", lambda e: _state(e)
                          if e.data["entity_id"] == c.STATE_ENTITY_ID else None)
    await tick(hass, entry, freezer, later(minutes=5))
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    await tick(hass, entry, freezer, later(minutes=60))
    world.finish()
    await tick(hass, entry, freezer, later(minutes=3))

    assert [s[1] for s in states] == [F.SCHEDULED, F.AWAITING, F.STARTING, F.RUNNING,
                                      F.COMPLETED, F.IDLE]
    assert len(lines) == len(states)
    for (old, new), line in zip(states, lines, strict=True):
        assert line.startswith(f"{old} -> {new}")
        assert " corr=" in line and " src=" in line


async def test_same_state_is_a_noop_without_a_log_line(hass, freezer):
    _world, entry = await build(hass, freezer)
    lines = []
    hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, lambda e: lines.append(e.data["message"]))
    result = await entry.runtime_data.fsm.transition(F.IDLE, "test")
    assert result.status == "noop"
    assert lines == []


async def test_illegal_transition_raises_and_becomes_an_error(hass, freezer):
    world, entry = await build(hass, freezer)
    with pytest.raises(TransitionRefused):
        await entry.runtime_data.fsm.transition(F.STARTING, "test")
    assert fsm(entry) == F.IDLE
    # through the dispatcher, a refusal routes to enter_error
    async def _bad(**_):
        await entry.runtime_data.fsm.transition(F.COMPLETED, "test")
    entry.runtime_data.orchestrator._handlers["log_cut"] = _bad
    await dispatch(hass, entry, "log_cut", freezer=freezer)
    assert fsm(entry) == F.ERROR
    assert "Idle -> Completed refused" in world.notifications[-1]["message"]


def _refuse(monkeypatch, target: str) -> None:
    real = FsmWriter.transition

    async def transition(self, to_state, intent, source="orchestrator", note=""):
        if to_state == target:
            raise TransitionRefused(self.state, to_state, intent, "injected")
        return await real(self, to_state, intent, source, note)

    monkeypatch.setattr(FsmWriter, "transition", transition)


async def test_refused_scheduled_sends_no_prompt(hass, freezer, monkeypatch):
    world, entry = await build(hass, freezer)
    _refuse(monkeypatch, F.SCHEDULED)
    await tick(hass, entry, freezer, later(minutes=5))
    assert world.prompts() == []
    assert "prompt_user" not in entry.runtime_data.dispatcher.handled
    assert fsm(entry) == F.ERROR


async def test_refused_awaiting_sends_no_prompt_and_arms_nothing(hass, freezer, monkeypatch):
    world, entry = await build(hass, freezer)
    _refuse(monkeypatch, F.AWAITING)
    await tick(hass, entry, freezer, later(minutes=5))
    assert world.prompts() == []
    assert entry.runtime_data.store.day.ack_deadline == ""
    assert fsm(entry) == F.ERROR


async def test_refused_starting_sends_no_command(hass, freezer, monkeypatch):
    world, entry = await build(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    _refuse(monkeypatch, F.STARTING)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_START), freezer)
    assert world.calls == []
    assert fsm(entry) == F.ERROR


async def test_refused_skip_leaves_the_prompt_alone(hass, freezer, monkeypatch):
    world, entry = await build(hass, freezer)
    await tick(hass, entry, freezer, later(minutes=5))
    _refuse(monkeypatch, F.SKIPPED)
    before = len(world.notifications)
    await fire_action(hass, entry, world.last_prompt_action(c.ACT_SKIP), freezer)
    sent = world.notifications[before:]
    assert not any(n["message"] == "clear_notification" for n in sent)
    assert fsm(entry) == F.ERROR


async def test_refused_error_write_sends_no_error_notification(hass, freezer, monkeypatch):
    world, entry = await build(hass, freezer)
    _refuse(monkeypatch, F.ERROR)
    await dispatch(hass, entry, ("enter_error", {"error_context": "boom"}), freezer=freezer)
    assert fsm(entry) == F.IDLE
    assert entry.runtime_data.store.fsm.error_from == F.IDLE      # stamped before the write
    assert not any(n.get("title", "").endswith("Error") for n in world.notifications)
    await settle(hass, entry, freezer)                            # and no retry loop
