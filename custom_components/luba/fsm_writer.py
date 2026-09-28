"""The single FSM writer (design Q5; FSM spec v1.1, translated).

``FsmWriter.transition`` is the only code that assigns ``store.fsm.state`` (a
test checks the source for any other assignment). Contract, from the YAML
helper's spec:

1. read the current state fresh (callers never pass a from-state);
2. same state → ``noop`` (a success);
3. unknown or illegal target → raise ``TransitionRefused``;
4. write, then save the store **before** logging, so the logbook never shows
   a transition that a crash could lose;
5. log ``from -> to [note] corr=… src=…``.

Refusals RAISE rather than return a status: a Python caller cannot silently
drop an exception the way a YAML caller dropped ``_tr`` (review M2). The
dispatcher turns a refusal into ``enter_error``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import audit
from .const import TITLE
from .engine.fsm import STATES, is_legal
from .store import LubaStore

_LOGGER = logging.getLogger(__name__)


class TransitionRefused(Exception):
    """An intent asked for a transition the table does not allow."""

    def __init__(self, from_state: str, to_state: str, intent: str, reason: str) -> None:
        super().__init__(f"{intent}: {from_state} -> {to_state} refused ({reason})")
        self.from_state, self.to_state, self.intent, self.reason = from_state, to_state, intent, reason


@dataclass(frozen=True)
class TransitionResult:
    status: str               # "ok" | "noop"
    from_state: str
    to_state: str
    corr: str


def new_corr(intent: str) -> str:
    return f"{dt_util.utcnow().strftime('%Y%m%dT%H%M%S.%fZ')}_{intent}"


class FsmWriter:
    def __init__(self, hass: HomeAssistant, store: LubaStore,
                 on_change: Callable[[], None]) -> None:
        self._hass, self._store, self._on_change = hass, store, on_change

    @property
    def state(self) -> str:
        return self._store.fsm.state

    async def transition(self, to_state: str, intent: str, source: str = "orchestrator",
                         note: str = "") -> TransitionResult:
        from_state = self._store.fsm.state
        corr = new_corr(intent)
        if to_state == from_state:
            _LOGGER.debug("idempotent_noop %s corr=%s", to_state, corr)
            return TransitionResult("noop", from_state, to_state, corr)
        if to_state not in STATES:
            raise TransitionRefused(from_state, to_state, intent, "unknown state")
        if not is_legal(from_state, to_state):
            raise TransitionRefused(from_state, to_state, intent, "not in the transition table")

        fsm = self._store.fsm
        fsm.state = to_state
        fsm.last_transition_at = dt_util.now().isoformat()
        fsm.last_corr = corr
        await self._store.async_save()
        message = f"{from_state} -> {to_state}{f' [{note}]' if note else ''} corr={corr} src={source}"
        try:
            audit.log(self._hass, message, name=f"{TITLE} FSM")
        except Exception:  # noqa: BLE001 — the write already happened; the audit line is best-effort
            _LOGGER.warning("logbook write failed after a verified transition: %s", message)
        _LOGGER.info("%s", message)
        self._on_change()
        return TransitionResult("ok", from_state, to_state, corr)

    async def restore(self, to_state: str, source: str = "import") -> TransitionResult:
        """Set the state an import brings over (luba.import_yaml_state, cutover P4).

        A restore, not a transition: it copies where the YAML's FSM already is, so
        the legality table does not apply. The same save-then-log contract does.
        """
        from_state = self._store.fsm.state
        corr = new_corr("import_yaml_state")
        if to_state not in STATES:
            raise TransitionRefused(from_state, to_state, "import_yaml_state", "unknown state")
        if to_state == from_state:
            return TransitionResult("noop", from_state, to_state, corr)
        fsm = self._store.fsm
        fsm.state = to_state
        fsm.last_transition_at = dt_util.now().isoformat()
        fsm.last_corr = corr
        await self._store.async_save()
        message = f"{from_state} -> {to_state} [imported from the YAML] corr={corr} src={source}"
        audit.log(self._hass, message, name=f"{TITLE} FSM")
        _LOGGER.info("%s", message)
        self._on_change()
        return TransitionResult("ok", from_state, to_state, corr)
