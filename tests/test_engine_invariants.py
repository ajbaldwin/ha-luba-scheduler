"""Structural invariants (design Q9): the FSM table, the single writer, the single commander.

These replace the YAML suite's parse-level checks (``luba-tests``) with checks
on the Python source and on the executable transition table.
"""
import ast
from pathlib import Path

import pytest

from custom_components.luba.engine import fsm as F
from custom_components.luba.engine.fsm import LEGAL, STATES, is_legal
from custom_components.luba.intents import Orchestrator

PKG = Path(__file__).parent.parent / "custom_components" / "luba"
SOURCES = {p.relative_to(PKG).as_posix(): ast.parse(p.read_text(encoding="utf-8"))
           for p in PKG.rglob("*.py")}
ALL = set(STATES)

# Every pair an intent writes, and who writes it. Read from the handlers'
# guards, independently of fsm.py. The table must equal this exactly: a pair
# no intent writes is a hole, and a pair an intent writes that the table lacks
# would raise TransitionRefused at run time.
WRITES: dict[str, dict[str, str]] = {
    F.IDLE: {
        **{s: "schedule_day (stale carry-over sweep: any non-Idle, non-suspended state)"
           for s in ALL - {F.IDLE}},
        F.PAUSED: "close_window (weather-aborted docked job finalised)",
        F.SKIPPED: "close_window",
        F.COMPLETED: "log_completion",
        F.ERROR: "clear_error / close_window",
        F.OFFLINE: "telemetry_sync (offline exit to a dock-idle mode)",
    },
    F.SCHEDULED: {
        F.IDLE: "schedule_day",
        F.AWAITING: "reprompt (conditions lapsed)",
        # schedule_day over a held (suspended) carry-over job, which the sweep skips:
        F.PAUSED: "schedule_day", F.RETURNING: "schedule_day", F.SKIPPED: "schedule_day",
        F.COMPLETED: "schedule_day", F.ERROR: "schedule_day", F.OFFLINE: "schedule_day",
    },
    F.AWAITING: {F.SCHEDULED: "prompt_user", F.PAUSED: "conditions_recovered",
                 F.IDLE: "conditions_recovered"},
    F.STARTING: {F.AWAITING: "start_mow"},
    F.RUNNING: {F.STARTING: "telemetry_sync (verified start)",
                F.SCHEDULED: "telemetry_sync (adopted run)",
                F.AWAITING: "telemetry_sync (adopted run)",
                F.IDLE: "telemetry_sync (adopted run)",
                F.PAUSED: "telemetry_sync (resumed)",
                F.RETURNING: "telemetry_sync (return aborted)",
                F.OFFLINE: "telemetry_sync (back online mid-mow)",
                F.ERROR: "telemetry_sync (late start heals, error_from Starting only)"},
    F.PAUSED: {s: "telemetry_sync" for s in (F.SCHEDULED, F.AWAITING, F.STARTING, F.RUNNING,
                                             F.RETURNING, F.OFFLINE)},
    F.RETURNING: {s: "telemetry_sync" for s in (F.RUNNING, F.PAUSED, F.OFFLINE)},
    F.SKIPPED: {F.AWAITING: "handle_action (Skip)", F.PAUSED: "handle_action (Skip)"},
    F.COMPLETED: {F.RUNNING: "telemetry_idle", F.RETURNING: "telemetry_idle"},
    F.ERROR: {s: "enter_error" for s in ALL - {F.ERROR}},
    F.OFFLINE: {s: "telemetry_offline" for s in ALL - {F.IDLE, F.OFFLINE}},
}


def test_table_is_exactly_what_the_intents_write():
    assert set(LEGAL) == ALL
    for to_state in STATES:
        assert set(LEGAL[to_state]) == set(WRITES.get(to_state, {})), to_state


def test_no_charging_state():
    """Review M5: the hardware never reports MODE_CHARGING; the state is gone."""
    assert "Charging" not in STATES
    assert not any("Charging" in froms for froms in LEGAL.values())


@pytest.mark.parametrize("from_state", STATES)
def test_self_transitions_are_not_in_the_table(from_state):
    """Same state is the writer's noop, never a table entry."""
    assert not is_legal(from_state, from_state)


def test_every_transition_target_in_the_intents_is_a_state():
    """Literal targets are F.<STATE>; the one computed target is telemetry_sync's mode map."""
    targets, computed = set(), []
    for node in ast.walk(SOURCES["intents.py"]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "transition" and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Attribute):
                targets.add(getattr(F, arg.attr))
            else:
                computed.append(ast.unparse(arg))
    assert targets <= ALL
    assert computed == ["target"]                    # telemetry_sync: Paused / Returning


def test_intent_enum():
    """21 intents: the YAML's 23 minus the two Charging intents (M5)."""
    assert len(Orchestrator.INTENTS) == 21
    assert "charge_threshold_reached" not in Orchestrator.INTENTS
    assert "charging_timer_expired" not in Orchestrator.INTENTS


# ---- single writer / single commander -----------------------------------------------

def _state_assignments(tree: ast.AST) -> list[int]:
    """Lines assigning ``<something>.fsm.state`` or ``<fsm>.state`` on an fsm object."""
    lines = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            for sub in ast.walk(t):
                if (isinstance(sub, ast.Attribute) and sub.attr == "state"
                        and "fsm" in ast.unparse(sub.value)):
                    lines.append(node.lineno)
    return lines


def test_only_the_fsm_writer_assigns_fsm_state():
    offenders = {name: lines for name, tree in SOURCES.items()
                 if name != "fsm_writer.py" and (lines := _state_assignments(tree))}
    assert offenders == {}
    assert _state_assignments(SOURCES["fsm_writer.py"])        # the check can see one


MOWER_DOMAINS = {"lawn_mower", "mammotion"}


def _service_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, first-arg source) of every ``*.async_call(...)``."""
    return [(node.lineno, ast.unparse(node.args[0]) if node.args else "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "async_call"]


def test_only_the_commander_calls_services_on_the_mower():
    allowed = {
        "notifier.py": {"domain"},                   # notify.* / calendar, from config
        "intents.py": {"'homeassistant'"},           # update_entity (readiness refresh)
        "commander.py": {"domain"},                  # the one place mower calls happen
    }
    for name, tree in SOURCES.items():
        for line, first in _service_calls(tree):
            assert first in allowed.get(name, set()), f"{name}:{line} calls {first}"
    # and the commander's call sites name the mower domains, so the check has teeth
    commander = ast.unparse(SOURCES["commander.py"])
    assert '"lawn_mower"' in commander or "'lawn_mower'" in commander


def test_listeners_only_dispatch():
    """The thin-automation rule: no FSM access, no service calls, no store writes."""
    tree = SOURCES["listeners.py"]
    assert _service_calls(tree) == []
    src = ast.unparse(tree)
    assert ".transition(" not in src
    assert ".fsm" not in src
    assert "store." not in src.replace("co.store.day.ack_deadline", "")
    assert "commander" not in src and ".cmd." not in src


def test_no_naive_datetimes_in_the_integration():
    """Defect 27: every timestamp is aware. Ban datetime.now()/utcnow() and naive datetime(...)."""
    for name, tree in SOURCES.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                src = ast.unparse(node.func)
                assert src not in ("datetime.now", "datetime.utcnow", "datetime.datetime.now",
                                   "datetime", "datetime.datetime", "date.today"), \
                    f"{name}:{node.lineno} {src}(...)"
