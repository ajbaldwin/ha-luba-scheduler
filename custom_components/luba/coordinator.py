"""LubaCoordinator (P1: read-only). Reads every input, computes one Snapshot.

Recomputes on any input's state change and once a minute (lightning recency
ages out, the sun moves). ``delay_on`` clocks live in the store and a
point-in-time callback fires exactly when one expires.

P1 commands nothing: no mower, notify or calendar calls exist yet.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import const as c
from .engine.conditions import (Readings, Thresholds, adverse_terms, delayed_on, optimal_terms,
                                ready_terms)
from .engine.schedule import AngleResult, group_for, next_angle, select_group
from .mammotion import resolve
from .store import LubaStore

_LOGGER = logging.getLogger(__name__)
SUN = "sun.sun"
_MISSING = (None, STATE_UNKNOWN, STATE_UNAVAILABLE, "")


@dataclass
class Snapshot:
    readings: Readings
    now: datetime
    freq: int
    group: str                                  # wetness group selected ('' = both)
    optimal: bool
    optimal_terms: dict[str, bool]
    group_ok: dict[str, bool]
    group_terms: dict[str, dict[str, bool]]
    overseed_hold: dict[str, bool | None]       # None = no overseed authority configured
    adverse: bool
    adverse_terms: dict[str, bool]
    ready: bool
    ready_terms: dict[str, bool]
    window_close: datetime | None
    hard_stop: datetime | None
    angle: AngleResult
    unresolved_roles: list[str] = field(default_factory=list)


def options_with_defaults(entry: ConfigEntry) -> dict[str, Any]:
    return {**c.DEFAULTS, **entry.options}


class LubaCoordinator(DataUpdateCoordinator[Snapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: LubaStore) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=c.DOMAIN,
                         update_interval=timedelta(minutes=1))
        self.store = store
        self.opts = options_with_defaults(entry)
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_delay: CALLBACK_TYPE | None = None
        self._unsub_registry: CALLBACK_TYPE | None = None
        self.on_deadlines_changed: Callable[[], None] | None = None
        # Set by async_setup_entry (P2 runtime): fsm writer, dispatcher, orchestrator, …
        self.fsm = None
        self.dispatcher = None
        self.commander = None
        self.notifier = None
        self.orchestrator = None

    # ---- settings (owner-writable, exposed as select/number) -------------------

    @property
    def angle_options(self) -> list[int]:
        return [int(a) for a in self.opts[c.CONF_ANGLES]]

    @property
    def spacing_options(self) -> list[int]:
        return [int(s) for s in self.opts[c.CONF_SPACINGS]]

    @property
    def angle_1(self) -> int:
        value = self.store.settings.angle_1
        return value if value in self.angle_options else self.angle_options[0]

    @property
    def spacing(self) -> int:
        value = self.store.settings.spacing
        return value if value in self.spacing_options else self.spacing_options[0]

    @property
    def mower_name(self) -> str:
        """The owner's name for the mower (device registry), used in notifications."""
        device = dr.async_get(self.hass).async_get(self.opts.get(c.CONF_DEVICE, ""))
        return (device.name_by_user or device.name) if device else "Mower"

    @callback
    def async_update_settings(self, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(self.store.settings, key, value)
        self.store.async_delay_save()
        self.async_set_updated_data(self._compute())

    # ---- inputs -----------------------------------------------------------------

    def _role_entity(self, role: str) -> str | None:
        return resolve(self.hass, self.opts.get(c.CONF_ROLES, {}).get(role))

    def input_entity_ids(self) -> list[str]:
        ids = [SUN]
        for key in (c.CONF_SEASON, c.CONF_WEATHER, c.CONF_PRECIP_TYPE, c.CONF_PRECIP_CHANCE,
                    c.CONF_CANOPY, c.CONF_LIGHTNING_DISTANCE, c.CONF_LIGHTNING_STRIKE,
                    *c.CONF_DRY.values(), *c.CONF_MOW_ALLOWED.values()):
            if self.opts.get(key):
                ids.append(self.opts[key])
        for role in (c.ROLE_CAMERA, c.ROLE_RTK_FIX, c.ROLE_BATTERY):
            if entity_id := self._role_entity(role):
                ids.append(entity_id)
        return sorted(set(ids))

    def _state(self, entity_id: str | None) -> str | None:
        if not entity_id or (st := self.hass.states.get(entity_id)) is None:
            return None
        return None if st.state in _MISSING else st.state

    def _float(self, entity_id: str | None) -> float | None:
        try:
            value = self._state(entity_id)
            return float(value) if value is not None else None
        except ValueError:
            return None

    def _on(self, entity_id: str | None) -> bool | None:
        value = self._state(entity_id)
        return None if value is None else value == "on"

    def _time(self, entity_id: str | None) -> datetime | None:
        value = self._state(entity_id)
        parsed = dt_util.parse_datetime(value) if value else None
        return parsed if parsed and parsed.tzinfo else None

    def _sun_attr(self, attr: str) -> datetime | None:
        st = self.hass.states.get(SUN)
        raw = st.attributes.get(attr) if st else None
        if isinstance(raw, datetime):
            return raw
        return dt_util.parse_datetime(raw) if isinstance(raw, str) else None

    def gate_closed(self) -> bool:
        """The ONE gate reader. Unavailable/unknown/missing counts as OPEN (fail closed),
        whatever the polarity; the polarity option says what "on" means."""
        entity_id = self.opts.get(c.CONF_GATE)
        st = self.hass.states.get(entity_id) if entity_id else None
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        on = st.state == "on"
        return on if self.opts.get(c.CONF_GATE_POLARITY) == c.GATE_ON_CLOSED else not on

    def readings(self) -> Readings:
        o = self.opts
        sun = self._state(SUN)
        return Readings(
            season_on=self._on(o.get(c.CONF_SEASON)),
            sun_above=None if sun is None else sun == "above_horizon",
            canopy_f=self._float(o.get(c.CONF_CANOPY)),
            precip_chance=self._float(o.get(c.CONF_PRECIP_CHANCE)),
            precip_type=self._state(o.get(c.CONF_PRECIP_TYPE)),
            weather=self._state(o.get(c.CONF_WEATHER)),
            lightning_distance=self._float(o.get(c.CONF_LIGHTNING_DISTANCE)),
            lightning_last_strike=self._time(o.get(c.CONF_LIGHTNING_STRIKE)),
            camera=self._state(self._role_entity(c.ROLE_CAMERA)),
            rtk=self._state(self._role_entity(c.ROLE_RTK_FIX)),
            battery=self._float(self._role_entity(c.ROLE_BATTERY)),
            dry={g: self._on(o.get(c.CONF_DRY[g])) for g in c.GROUPS},
        )

    def thresholds(self) -> Thresholds:
        o = self.opts
        return Thresholds(
            canopy_min_f=o[c.CONF_CANOPY_MIN], canopy_max_f=o[c.CONF_CANOPY_MAX],
            precip_chance_max=o[c.CONF_PRECIP_MAX], lightning_radius=o[c.CONF_LIGHTNING_RADIUS],
            lightning_recency_s=o[c.CONF_LIGHTNING_RECENCY] * 60,
            fresh_start_floor=o[c.CONF_START_FLOOR])

    # ---- compute ----------------------------------------------------------------

    def _delayed(self, key: str, raw: bool, now: datetime, delay_s: float) -> bool:
        state, since = delayed_on(raw, self.store.on_since(key), now, delay_s)
        if self.store.set_on_since(key, since):
            self.store.async_delay_save()
        return state

    def _compute(self) -> Snapshot:
        now = dt_util.now()
        r, t = self.readings(), self.thresholds()
        s = self.store
        freq = s.settings.cuts_per_group
        group = select_group(s.session.active_group, s.day.scheduled_group, now.weekday(), freq)
        delay_s = self.opts[c.CONF_OPTIMAL_DELAY] * 60

        opt_terms = optimal_terms(r, t, group)
        optimal = self._delayed("optimal", all(opt_terms.values()), now, delay_s)
        group_terms = {g: optimal_terms(r, t, g) for g in c.GROUPS}
        group_ok = {g: self._delayed(g, all(group_terms[g].values()), now, delay_s)
                    for g in c.GROUPS}
        overseed_hold = {}
        for g in c.GROUPS:
            source = self.opts.get(c.CONF_MOW_ALLOWED[g])
            # Unavailable permission holds: seedlings are the costlier mistake.
            overseed_hold[g] = None if not source else self._on(source) is not True

        adv_terms = adverse_terms(r, t, now)
        rdy_terms = ready_terms(r, t, s.fsm.state)
        setting = self._sun_attr("next_setting")
        cutoff = timedelta(minutes=self.opts[c.CONF_CUTOFF_MIN])
        stamped = s.day.scheduled_group
        angle = next_angle(freq, stamped, s.counters.cuts.get(stamped, 0), self.angle_1)
        self._schedule_delay_expiry(now, delay_s)
        return Snapshot(
            readings=r, now=now, freq=freq, group=group,
            optimal=optimal, optimal_terms=opt_terms,
            group_ok=group_ok, group_terms=group_terms, overseed_hold=overseed_hold,
            adverse=any(adv_terms.values()), adverse_terms=adv_terms,
            ready=all(rdy_terms.values()), ready_terms=rdy_terms,
            window_close=setting - cutoff if setting else None,
            hard_stop=self._sun_attr("next_dusk"),
            angle=angle,
            unresolved_roles=[role for role in c.MOWER_ROLES if not self._role_entity(role)],
        )

    def _schedule_delay_expiry(self, now: datetime, delay_s: float) -> None:
        """Recompute exactly when the earliest pending delay_on clock expires."""
        if self._unsub_delay:
            self._unsub_delay()
            self._unsub_delay = None
        pending = [since + timedelta(seconds=delay_s)
                   for key in ("optimal", *c.GROUPS)
                   if (since := self.store.on_since(key)) and since + timedelta(seconds=delay_s) > now]
        if pending:
            wait = (min(pending) - now).total_seconds() + 0.1
            self._unsub_delay = async_call_later(self.hass, wait, self._on_delay_expiry)

    @callback
    def _on_delay_expiry(self, _now: datetime) -> None:
        self._unsub_delay = None
        self.async_set_updated_data(self._compute())

    @callback
    def recompute(self) -> Snapshot:
        """A fresh snapshot, published to every entity. Handlers call this before deciding."""
        snap = self._compute()
        self.async_set_updated_data(snap)
        return snap

    @callback
    def async_arm_deadlines(self) -> None:
        if self.on_deadlines_changed:
            self.on_deadlines_changed()

    async def _async_update_data(self) -> Snapshot:
        return self._compute()

    # ---- lifecycle ----------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        self._subscribe()
        self._unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated)

    @callback
    def _subscribe(self) -> None:
        if self._unsub_state:
            self._unsub_state()
        self._unsub_state = async_track_state_change_event(
            self.hass, self.input_entity_ids(), self._on_input_changed)

    @callback
    def _on_input_changed(self, _event: Event) -> None:
        self.async_set_updated_data(self._compute())

    @callback
    def _on_registry_updated(self, event: Event) -> None:
        # A bound Mammotion entity re-slugged (or one appeared/vanished): follow it.
        if event.data.get("action") == "update" and "old_entity_id" not in event.data:
            return
        self._subscribe()
        self.async_set_updated_data(self._compute())

    @callback
    def async_stop(self) -> None:
        for unsub in (self._unsub_state, self._unsub_delay, self._unsub_registry):
            if unsub:
                unsub()
        self._unsub_state = self._unsub_delay = self._unsub_registry = None
