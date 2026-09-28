"""Persistent state for the one Luba entry: a versioned Home Assistant Store.

A restart is NOT a session boundary (YAML v3.1.25): nothing here resets on
load. The shape is the whole of design Q4 so the contract is fixed now; P1
only reads most of it (the engine that writes the FSM/session/day fields
arrives in P2).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION


def _from(cls, raw: dict | None):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (raw or {}).items() if k in names})


@dataclass
class Fsm:
    state: str = "Idle"
    prior_state: str = ""
    error_from: str = ""
    last_transition_at: str = ""      # ISO-8601 with offset
    last_corr: str = ""


@dataclass
class Session:
    start: str = ""
    battery_start: float | None = None
    work_area: str = ""
    recharge_count: int = 0
    abort_reason: str = ""
    active_group: str = ""


@dataclass
class Day:
    scheduled_group: str = ""
    evaluated_at: str = ""            # ISO datetime: schedule_day handled this date
    ack_deadline: str = ""
    prompt_id: str = ""
    skip_recorded_for: str = ""


@dataclass
class Counters:
    cuts: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0})
    last_counted_cut: str = ""
    last_logged_cut: str = ""
    week_of: str = ""


@dataclass
class Settings:
    """Owner-set (and later rotation-set) mowing settings, exposed as select/number."""
    cuts_per_group: int = 1
    angle_1: int | None = None        # None = first entry of the configured list
    spacing: int | None = None
    cutting_height: int = 70
    auto_start: bool = False


@dataclass
class Conditions:
    """delay_on clocks, persisted so a held reading survives a restart."""
    on_since: dict[str, str] = field(default_factory=dict)   # key -> ISO timestamp


class LubaStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.fsm = Fsm()
        self.session = Session()
        self.day = Day()
        self.counters = Counters()
        self.settings = Settings()
        self.conditions = Conditions()

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self.fsm = _from(Fsm, raw.get("fsm"))
        self.session = _from(Session, raw.get("session"))
        self.day = _from(Day, raw.get("day"))
        self.counters = _from(Counters, raw.get("counters"))
        self.settings = _from(Settings, raw.get("settings"))
        self.conditions = _from(Conditions, raw.get("conditions"))

    def _data(self) -> dict[str, Any]:
        return {"fsm": asdict(self.fsm), "session": asdict(self.session),
                "day": asdict(self.day), "counters": asdict(self.counters),
                "settings": asdict(self.settings), "conditions": asdict(self.conditions)}

    async def async_save(self) -> None:
        await self._store.async_save(self._data())

    def async_delay_save(self) -> None:
        self._store.async_delay_save(self._data, 1)

    async def async_remove(self) -> None:
        await self._store.async_remove()

    def on_since(self, key: str) -> datetime | None:
        value = self.conditions.on_since.get(key)
        return datetime.fromisoformat(value) if value else None

    def set_on_since(self, key: str, when: datetime | None) -> bool:
        """Record a delay_on clock; True if it changed (caller schedules a save)."""
        value = when.isoformat() if when else None
        if self.conditions.on_since.get(key) == value:
            return False
        if value is None:
            self.conditions.on_since.pop(key, None)
        else:
            self.conditions.on_since[key] = value
        return True
