"""Shadow comparison (design Q10, P3): the port's FSM against the YAML package's.

In shadow mode both systems consume the same events. When the owner points the
Mode options step at the YAML FSM entity, ``sensor.luba_state`` publishes
``yaml_state``, ``diverged`` and ``diverged_since``. A divergence is logged to
the logbook once it has lasted ``SETTLE_S`` (the two systems transition a few
seconds apart, and those blips are noise), and again when it clears, with how
long it lasted — that pair is what the daily P3 review reads.

Read-only: nothing here writes the YAML entity or the port's FSM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from . import audit
from . import const as c
from .engine import fsm as F

SETTLE_S = 300
# YAML states the port represents differently. A docked held job is Charging in
# the YAML and Paused (charging on) here (review M5).
EQUIVALENT = {"Charging": F.PAUSED}


class ShadowCompare:
    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        self.hass, self.co = hass, coordinator
        self._since: datetime | None = None
        self._pair: tuple[str, str] | None = None
        self._logged = False
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_listener: CALLBACK_TYPE | None = None

    @property
    def entity_id(self) -> str | None:
        return self.co.opts.get(c.CONF_YAML_STATE)

    def yaml_state(self) -> str | None:
        st = self.hass.states.get(self.entity_id) if self.entity_id else None
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            return None
        return st.state

    def diverged(self) -> bool | None:
        """None when there is nothing to compare against."""
        yaml = self.yaml_state()
        if yaml is None:
            return None
        return EQUIVALENT.get(yaml, yaml) != self.co.store.fsm.state

    @callback
    def evaluate(self) -> None:
        """Track the current divergence episode. Idempotent: safe on every snapshot."""
        diverged, yaml, port = self.diverged(), self.yaml_state(), self.co.store.fsm.state
        if diverged:
            if self._since is None:
                self._since, self._logged = dt_util.utcnow(), False
                self._unsub_timer = async_call_later(self.hass, SETTLE_S, self._settled)
            self._pair = (port, yaml)
            return
        if self._since is not None:
            if self._logged:
                minutes = round((dt_util.utcnow() - self._since).total_seconds() / 60)
                audit.log(self.hass, f"shadow: agrees with the YAML again ({port}) after "
                                     f"{minutes} min")
            self._clear()

    @callback
    def _settled(self, _now: datetime) -> None:
        self._unsub_timer = None
        if self._since is not None and self.diverged() and not self._logged:
            port, yaml = self._pair or (self.co.store.fsm.state, self.yaml_state())
            audit.log(self.hass, f"shadow: diverged from the YAML for {SETTLE_S // 60} min — "
                                 f"port {port}, YAML {yaml}")
            self._logged = True

    def _clear(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
        self._unsub_timer, self._since, self._pair, self._logged = None, None, None, False

    def attributes(self) -> dict[str, Any]:
        if not self.entity_id:
            return {}
        self.evaluate()
        return {"yaml_state": self.yaml_state(), "diverged": self.diverged(),
                "diverged_since": self._since.isoformat() if self._since else None}

    @callback
    def async_start(self) -> None:
        self._unsub_listener = self.co.async_add_listener(self.evaluate)
        self.evaluate()

    @callback
    def async_stop(self) -> None:
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None
        self._clear()
