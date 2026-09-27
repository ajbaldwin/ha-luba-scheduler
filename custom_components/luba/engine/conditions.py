"""Mowing conditions: permission (optimal), danger (adverse) and mower readiness.

Ported from the YAML package's template sensors (PRD §5.14) and
``evaluate_readiness``. Each function returns its individual terms, so the
entities can publish WHY as attributes, not just the verdict.

Failure posture is per term and deliberate — carried over unchanged:

* optimal fails CLOSED: an unreadable canopy, precip chance or dry-grass
  reading withholds permission.
* adverse fails OPEN on its weather terms (an unreadable canopy is not "too
  hot") but CLOSED on darkness: after sunset it demands an affirmative
  camera ``Light`` to keep mowing, because losing cloud telemetry after dark
  should dock the mower, not license it.
* readiness is an allowlist: only RTK ``Fix`` and camera ``Light`` pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

PRECIP_TYPES_ADVERSE = frozenset({"rain", "hail", "rain_hail"})
WEATHER_ADVERSE = frozenset({"pouring", "hail", "snowy", "snowy-rainy"})
RTK_FIX = "Fix"
CAMERA_LIGHT = "Light"
FSM_ERROR = "Error"


@dataclass(frozen=True)
class Readings:
    """Input states at one instant. None = unknown/unavailable/unparseable."""
    season_on: bool | None = None
    sun_above: bool | None = None
    canopy_f: float | None = None
    precip_chance: float | None = None
    precip_type: str | None = None
    weather: str | None = None
    lightning_distance: float | None = None
    lightning_last_strike: datetime | None = None
    camera: str | None = None
    rtk: str | None = None
    battery: float | None = None
    dry: dict[str, bool | None] = field(default_factory=dict)   # {"A": .., "B": ..}


@dataclass(frozen=True)
class Thresholds:
    canopy_min_f: float = 50
    canopy_max_f: float = 90
    precip_chance_max: float = 51          # permission needs chance < this
    lightning_radius: float = 5            # in the distance sensor's own unit
    lightning_recency_s: float = 300
    fresh_start_floor: float = 95


def dry_for(readings: Readings, group: str) -> bool:
    """The selected group's dry-grass verdict; an undetermined group needs both dry."""
    if group in ("A", "B"):
        return readings.dry.get(group) is True
    return readings.dry.get("A") is True and readings.dry.get("B") is True


def optimal_terms(r: Readings, t: Thresholds, group: str) -> dict[str, bool]:
    """Permission to START a mow. Every term must hold (the caller adds delay_on)."""
    return {
        "season": r.season_on is True,
        "daylight": r.sun_above is True,
        "canopy_in_range": r.canopy_f is not None and t.canopy_min_f <= r.canopy_f <= t.canopy_max_f,
        "precip_chance_low": r.precip_chance is not None and r.precip_chance < t.precip_chance_max,
        "dry": dry_for(r, group),
    }


def adverse_terms(r: Readings, t: Thresholds, now: datetime) -> dict[str, bool]:
    """Immediate danger: any term aborts a run. NOT the inverse of optimal."""
    strike_recent = (
        r.lightning_last_strike is not None
        and (now - r.lightning_last_strike).total_seconds() < t.lightning_recency_s
    )
    return {
        "precipitation": r.precip_type in PRECIP_TYPES_ADVERSE,
        "severe_weather": r.weather in WEATHER_ADVERSE,
        "lightning": (r.lightning_distance is not None
                      and r.lightning_distance < t.lightning_radius and strike_recent),
        "heat": r.canopy_f is not None and r.canopy_f > t.canopy_max_f,
        "darkness": r.sun_above is False and r.camera != CAMERA_LIGHT,
    }


def ready_terms(r: Readings, t: Thresholds, fsm_state: str) -> dict[str, bool]:
    """Mower readiness for a FRESH start (a resume uses a lower floor, later)."""
    return {
        "season": r.season_on is True,
        "rtk_fix": r.rtk == RTK_FIX,
        "battery": r.battery is not None and r.battery >= t.fresh_start_floor,
        "daylight": r.camera == CAMERA_LIGHT,
        "not_error": fsm_state != FSM_ERROR,
    }


def delayed_on(raw: bool, on_since: datetime | None, now: datetime,
               delay_s: float) -> tuple[bool, datetime | None]:
    """``delay_on`` as a pure function over a persisted on-since timestamp.

    Returns (state, new_on_since). The timestamp survives a restart, so a
    reading that has held for the delay stays on across one.
    """
    if not raw:
        return False, None
    since = on_since or now
    return (now - since).total_seconds() >= delay_s, since
