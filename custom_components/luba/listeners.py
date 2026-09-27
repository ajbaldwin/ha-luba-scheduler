"""The 18 thin automations, as listeners. Each one only ENQUEUES an intent.

A test asserts this module never writes the FSM or calls a mower service: the
"thin automation" rule becomes "listeners only dispatch". The one exception
is the YAML's documented exemption (#12): the gate-zone crossing alert
notifies directly, since it makes no decision and touches no state.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (async_call_later, async_track_point_in_time,
                                         async_track_state_change_event,
                                         async_track_time_change, async_track_time_interval)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from . import const as c
from .mammotion import resolve

_LOGGER = logging.getLogger(__name__)
NOTIFICATION_ACTION = "mobile_app_notification_action"


def _hms(value: str) -> tuple[int, int, int]:
    h, m, s = (int(p) for p in (value.split(":") + ["0", "0"])[:3])
    return h, m, s


class Listeners:
    def __init__(self, hass: HomeAssistant, coordinator, dispatch: Callable[..., bool],
                 notifier) -> None:
        self.hass, self.co, self._dispatch, self._notifier = hass, coordinator, dispatch, notifier
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._pending: dict[str, CALLBACK_TYPE] = {}
        self._last: dict[str, Any] = {}
        self._started_at: datetime = dt_util.utcnow()

    @property
    def opts(self) -> dict[str, Any]:
        return self.co.opts

    def _role(self, role: str) -> str | None:
        return resolve(self.hass, self.opts.get(c.CONF_ROLES, {}).get(role))

    # ---- lifecycle ------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        o = self.opts
        h, m, s = _hms(o[c.CONF_SCHEDULER_TIME])
        self._unsubs += [
            async_track_time_change(self.hass, self._on_scheduler_time, hour=h, minute=m, second=s),
            async_track_time_change(self.hass, self._on_rotation_time,
                                    **dict(zip(("hour", "minute", "second"),
                                               _hms(o[c.CONF_ROTATION_TIME]), strict=True))),
            async_track_time_interval(self.hass, self._on_readiness_tick, timedelta(minutes=15)),
            async_track_time_interval(self.hass, self._on_adverse_tick, timedelta(minutes=5)),
            self.hass.bus.async_listen(NOTIFICATION_ACTION, self._on_action),
            self.co.async_add_listener(self._on_snapshot),
            async_at_started(self.hass, self._on_started),
        ]
        if gate := o.get(c.CONF_GATE):
            self._unsubs.append(async_track_state_change_event(self.hass, [gate], self._on_gate))
        self._subscribe_mower()
        self.co.on_deadlines_changed = self.async_arm_deadlines
        self._on_snapshot()
        self._on_gate()

    @callback
    def async_stop(self) -> None:
        for unsub in [*self._unsubs, *self._timers.values(), *self._pending.values()]:
            unsub()
        self._unsubs.clear()
        self._timers.clear()
        self._pending.clear()
        self.co.on_deadlines_changed = None

    @callback
    def _subscribe_mower(self) -> None:
        ids = [e for e in (self._role(c.ROLE_ACTIVITY), self._role(c.ROLE_PROGRESS),
                           self._role(c.ROLE_WORK_AREA)) if e]
        if ids:
            self._unsubs.append(async_track_state_change_event(self.hass, ids, self._on_mower))

    def _in_startup_grace(self) -> bool:
        return (dt_util.utcnow() - self._started_at).total_seconds() < c.STARTUP_GRACE_S

    # ---- time triggers --------------------------------------------------------------

    @callback
    def _on_started(self, _hass: HomeAssistant) -> None:
        self._started_at = dt_util.utcnow()
        self._dispatch("reboot_recover")                              # #7

    @callback
    def _on_scheduler_time(self, _now: datetime) -> None:
        self._dispatch("schedule_day")                                # #1
        self._dispatch("conditions_recovered", trigger_source="floor")  # #8 floor tick

    @callback
    def _on_rotation_time(self, now: datetime) -> None:
        if dt_util.as_local(now).weekday() == 0:                     # #2, Mondays
            self._dispatch("rotate_settings")

    @callback
    def _on_readiness_tick(self, _now: datetime) -> None:
        self._dispatch("evaluate_readiness")                          # #6

    @callback
    def _on_adverse_tick(self, _now: datetime) -> None:
        if self.co.data and self.co.data.adverse:                     # #13 re-check
            self._dispatch("adverse_abort")

    @callback
    def async_arm_deadlines(self) -> None:
        """(Re)arm the point-in-time triggers: ack deadline, window close, hard stop."""
        snap = self.co.data
        wanted = {
            "reprompt": self.co.store.day.ack_deadline,                          # #9
            "close_window": snap.window_close.isoformat() if snap and snap.window_close else "",  # #10
            "hard_stop": snap.hard_stop.isoformat() if snap and snap.hard_stop else "",  # #17
        }
        for intent, when_iso in wanted.items():
            if self._last.get(f"deadline_{intent}") == when_iso:
                continue
            self._last[f"deadline_{intent}"] = when_iso
            if unsub := self._timers.pop(intent, None):
                unsub()
            when = dt_util.parse_datetime(when_iso) if when_iso else None
            if when is None:
                continue
            if when <= dt_util.utcnow():
                # A deadline that passed while HA was down fires once, now (design Q4),
                # except the sun-derived ones, which simply roll to tomorrow.
                if intent == "reprompt":
                    self._dispatch(intent)
                continue
            self._timers[intent] = async_track_point_in_time(
                self.hass, self._fire(intent), when)

    def _fire(self, intent: str) -> Callable[[datetime], None]:
        @callback
        def _fired(_now: datetime) -> None:
            self._timers.pop(intent, None)
            self._last.pop(f"deadline_{intent}", None)
            self._dispatch(intent)
        return _fired

    # ---- state triggers -------------------------------------------------------------

    @callback
    def _on_snapshot(self) -> None:
        snap = self.co.data
        if snap is None:
            return
        for key, value, intent, ctx in (
                ("optimal", snap.optimal, "conditions_recovered", {}),    # #8 edge
                ("ready", snap.ready, "conditions_recovered", {}),        # #8 edge
                ("adverse", snap.adverse, "adverse_abort", {})):          # #13 edge
            before = self._last.get(key)
            self._last[key] = value
            if value and before is False:
                self._dispatch(intent, **ctx)
        self.async_arm_deadlines()

    @callback
    def _on_gate(self, _event: Event | None = None) -> None:
        """#11: the gate closed (an edge, whatever the sensor's polarity)."""
        gate_closed = self._gate_closed()
        before = self._last.get("gate")
        self._last["gate"] = gate_closed
        if gate_closed and before is False:
            self._dispatch("gate_recover")

    def _gate_closed(self) -> bool:
        entity_id = self.opts.get(c.CONF_GATE)
        st = self.hass.states.get(entity_id) if entity_id else None
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        on = st.state == "on"
        return on if self.opts.get(c.CONF_GATE_POLARITY) == c.GATE_ON_CLOSED else not on

    @callback
    def _on_mower(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        new_state = new.state if new else None
        old_state = old.state if old else None
        if entity_id == self._role(c.ROLE_ACTIVITY):
            self._on_activity(old_state, new_state)
        elif entity_id == self._role(c.ROLE_PROGRESS):
            if _float(new_state) > 99 >= _float(old_state):
                self._dispatch("log_cut")                              # #18
        elif entity_id == self._role(c.ROLE_WORK_AREA):
            self._on_work_area(old_state, new_state)

    @callback
    def _on_activity(self, old: str | None, new: str | None) -> None:
        if new == old:
            return                          # attribute-only update: no edge, timers keep running
        if new:
            self._dispatch("telemetry_sync", mode_value=new)           # #4
        self._cancel_pending("offline")
        self._cancel_pending("idle")
        if new in (STATE_UNAVAILABLE, STATE_UNKNOWN, None):            # #5
            self._pending["offline"] = async_call_later(
                self.hass, self.opts[c.CONF_OFFLINE_TIMEOUT] * 60, self._held("offline"))
        elif new == c.MODE_READY:                                      # #18b
            self._pending["idle"] = async_call_later(
                self.hass, self.opts[c.CONF_IDLE_RECONCILE] * 60, self._held("idle"))

    def _held(self, which: str) -> Callable[[datetime], None]:
        intent = {"offline": "telemetry_offline", "idle": "telemetry_idle"}[which]

        @callback
        def _fired(_now: datetime) -> None:
            self._pending.pop(which, None)
            if not self._in_startup_grace():
                self._dispatch(intent)
        return _fired

    def _cancel_pending(self, which: str) -> None:
        if unsub := self._pending.pop(which, None):
            unsub()

    @callback
    def _on_work_area(self, old: str | None, new: str | None) -> None:
        """#12: the mower crossed from a Group A zone into a Group B zone (through the gate)."""
        names = {g: {_zone_name(b.get(c.BIND_NAME, "")) for b in bindings}
                 for g, bindings in self.opts.get(c.CONF_ZONES, {}).items()}
        if old in names.get("A", set()) and new in names.get("B", set()):
            self.hass.async_create_task(self._notifier.notify(
                f"{self.co.mower_name} — Close the Gate",
                f"{self.co.mower_name} just crossed from {old} into {new}. Close the gate behind it."))

    @callback
    def _on_action(self, event: Event) -> None:
        action = str(event.data.get("action", ""))
        if action.startswith(c.ACTION_PREFIX):
            self._dispatch("handle_action", action=action)             # #3


def _float(value: str | None) -> float:
    try:
        return float(value) if value is not None else -1.0
    except ValueError:
        return -1.0


def _zone_name(original_name: str) -> str:
    """Mammotion names area switches "Area <zone>"; work_area reports "<zone>"."""
    return original_name.removeprefix("Area ").strip()
