"""optimal / adverse / readiness terms — ported from templates.yaml + evaluate_readiness."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.luba.engine.conditions import (
    Readings, Thresholds, adverse_terms, delayed_on, dry_for, optimal_terms, ready_terms)

NOW = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
T = Thresholds()
GOOD = Readings(season_on=True, sun_above=True, canopy_f=70, precip_chance=10,
                precip_type="none", weather="sunny", lightning_distance=20,
                lightning_last_strike=NOW - timedelta(days=2), camera="Light", rtk="Fix",
                battery=100, dry={"A": True, "B": True})


def test_good_day_is_optimal_not_adverse_and_ready():
    assert all(optimal_terms(GOOD, T, "A").values())
    assert not any(adverse_terms(GOOD, T, NOW).values())
    assert all(ready_terms(GOOD, T, "Idle").values())


@pytest.mark.parametrize("change, term", [
    ({"season_on": False}, "season"),
    ({"sun_above": False}, "daylight"),
    ({"canopy_f": 49.9}, "canopy_in_range"),
    ({"canopy_f": 90.1}, "canopy_in_range"),
    ({"canopy_f": None}, "canopy_in_range"),        # unreadable fails closed
    ({"precip_chance": 51}, "precip_chance_low"),    # strictly below 51
    ({"precip_chance": None}, "precip_chance_low"),
])
def test_optimal_terms_fail(change, term):
    terms = optimal_terms(replace(GOOD, **change), T, "A")
    assert terms[term] is False
    assert sum(not v for v in terms.values()) == 1


def test_optimal_canopy_bounds_inclusive():
    assert optimal_terms(replace(GOOD, canopy_f=50), T, "A")["canopy_in_range"]
    assert optimal_terms(replace(GOOD, canopy_f=90), T, "A")["canopy_in_range"]


def test_dry_reads_only_the_selected_group():
    r = replace(GOOD, dry={"A": True, "B": False})
    assert dry_for(r, "A") and not dry_for(r, "B")
    assert not dry_for(r, "")                         # undetermined -> both required
    assert not dry_for(replace(GOOD, dry={"A": None, "B": True}), "A")


@pytest.mark.parametrize("change, term", [
    ({"precip_type": "rain"}, "precipitation"),
    ({"precip_type": "rain_hail"}, "precipitation"),
    ({"weather": "pouring"}, "severe_weather"),
    ({"weather": "snowy-rainy"}, "severe_weather"),
    ({"lightning_distance": 4.9, "lightning_last_strike": NOW - timedelta(seconds=299)}, "lightning"),
    ({"canopy_f": 90.5}, "heat"),
    ({"sun_above": False, "camera": "Dark"}, "darkness"),
    ({"sun_above": False, "camera": None}, "darkness"),   # lost telemetry after dark docks
])
def test_adverse_terms_trip(change, term):
    assert adverse_terms(replace(GOOD, **change), T, NOW)[term] is True


@pytest.mark.parametrize("change", [
    {"lightning_distance": 4, "lightning_last_strike": NOW - timedelta(seconds=300)},  # stale
    {"lightning_distance": 5, "lightning_last_strike": NOW},                            # at radius
    {"lightning_distance": 1, "lightning_last_strike": None},                           # no time
    {"canopy_f": None},                                   # unreadable heat fails open
    {"sun_above": False, "camera": "Light"},              # usable twilight keeps mowing
    {"sun_above": None, "camera": "Dark"},                # unknown sun is not below horizon
])
def test_adverse_terms_hold(change):
    assert not any(adverse_terms(replace(GOOD, **change), T, NOW).values())


@pytest.mark.parametrize("change, term", [
    ({"rtk": "Float"}, "rtk_fix"),
    ({"rtk": None}, "rtk_fix"),
    ({"battery": 94.9}, "battery"),
    ({"camera": "Dark"}, "daylight"),
    ({"season_on": None}, "season"),
])
def test_ready_terms_fail(change, term):
    assert ready_terms(replace(GOOD, **change), T, "Idle")[term] is False


def test_ready_blocked_by_error_state():
    assert ready_terms(GOOD, T, "Error")["not_error"] is False


def test_delayed_on():
    assert delayed_on(False, NOW, NOW, 300) == (False, None)
    assert delayed_on(True, None, NOW, 300) == (False, NOW)
    since = NOW - timedelta(seconds=299)
    assert delayed_on(True, since, NOW, 300) == (False, since)
    since = NOW - timedelta(seconds=300)
    assert delayed_on(True, since, NOW, 300) == (True, since)
