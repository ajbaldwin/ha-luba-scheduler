"""The mower FSM: states and the executable transition table.

The YAML helper deliberately did not enforce legality ("the orchestrator owns
that knowledge"), so the table lived only in the PRD and drifted from the code
(review D1). Here the writer rejects any pair not listed, so the table is the
code. It is the union of what the YAML intents actually write, from reading
every guard (not the PRD summary), minus the ``Charging`` state: the hardware
never reports ``MODE_CHARGING`` (review M5, 0 occurrences in 20 days), so a
docked, held job is ``Paused`` with the charging sensor on.
"""
from __future__ import annotations

IDLE = "Idle"
SCHEDULED = "Scheduled"
AWAITING = "Awaiting Acknowledgment"
STARTING = "Starting"
RUNNING = "Running"
RETURNING = "Returning"
PAUSED = "Paused"
SKIPPED = "Skipped Today"
COMPLETED = "Completed"
ERROR = "Error"
OFFLINE = "Offline"

STATES: tuple[str, ...] = (IDLE, SCHEDULED, AWAITING, STARTING, RUNNING, RETURNING, PAUSED,
                           SKIPPED, COMPLETED, ERROR, OFFLINE)
_ALL = frozenset(STATES)

# to_state -> the from_states any intent may write it from.
LEGAL: dict[str, frozenset[str]] = {
    # close_window, log_completion, clear_error, telemetry (Offline exit), and
    # schedule_day's stale carry-over sweep, which can find any state.
    IDLE: _ALL - {IDLE},
    # schedule_day (after the sweep, or over a held carry-over job in any
    # state but an in-flight start) and reprompt (conditions lapsed).
    SCHEDULED: _ALL - {SCHEDULED, STARTING, RUNNING},
    # prompt_user (from Scheduled) and conditions_recovered (held job).
    AWAITING: frozenset({SCHEDULED, PAUSED, IDLE}),
    # start_mow only ever starts from a prompt, owner-tapped or auto.
    STARTING: frozenset({AWAITING}),
    # telemetry MODE_WORKING. Error only heals when it came from Starting —
    # the intent checks error_from; the table admits the pair.
    RUNNING: frozenset({STARTING, SCHEDULED, AWAITING, IDLE, PAUSED, RETURNING, OFFLINE, ERROR}),
    PAUSED: frozenset({SCHEDULED, AWAITING, STARTING, RUNNING, RETURNING, OFFLINE}),
    RETURNING: frozenset({RUNNING, PAUSED, OFFLINE}),
    SKIPPED: frozenset({AWAITING, PAUSED}),
    COMPLETED: frozenset({RUNNING, RETURNING}),
    ERROR: _ALL - {ERROR},
    OFFLINE: _ALL - {IDLE, OFFLINE},
}

# Live-session states: hardware must be reconciled after a restart.
SESSION_STATES = frozenset({RUNNING, PAUSED, RETURNING})


def is_legal(from_state: str, to_state: str) -> bool:
    return from_state in LEGAL.get(to_state, frozenset())
