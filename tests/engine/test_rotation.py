"""Weekly rotation: one step per week through the owner's lists; seasonal tables."""
from datetime import date

import pytest

from custom_components.luba.engine.rotation import (next_in, seasonal_cuts_per_group,
                                                    seasonal_height)

ANGLES = [12, 48, 24, 60, 36]


def test_rotation_advances_exactly_one_step_around_the_cycle():
    seen, current = [], ANGLES[0]
    for _ in ANGLES:
        current = next_in(ANGLES, current)
        seen.append(current)
    assert seen == [48, 24, 60, 36, 12]                  # every value, then back to the start


@pytest.mark.parametrize("drifted", [None, 99, -1])
def test_an_unknown_current_value_restarts_at_the_first_entry(drifted):
    assert next_in(ANGLES, drifted) == ANGLES[0]


def test_an_empty_sequence_is_an_error_not_a_divide_by_zero():
    with pytest.raises(ValueError):
        next_in([], 12)


@pytest.mark.parametrize(("d", "height"), [
    (date(2026, 8, 3), 100), (date(2026, 8, 10), 95), (date(2026, 8, 17), 85),
    (date(2026, 8, 24), 80), (date(2026, 8, 31), 75),            # August steps down weekly
    (date(2026, 9, 7), 70), (date(2026, 10, 5), 75),            # flat months
    (date(2026, 5, 4), 75), (date(2026, 5, 11), 80),            # weeks 1 and 3 are 5 mm lower
])
def test_seasonal_height(d, height):
    assert seasonal_height(d) == height


@pytest.mark.parametrize(("d", "cuts"), [
    (date(2026, 4, 14), 1), (date(2026, 4, 15), 3), (date(2026, 6, 30), 3),
    (date(2026, 7, 15), 1), (date(2026, 8, 14), 1), (date(2026, 8, 15), 2),
    (date(2026, 9, 30), 3), (date(2026, 10, 14), 3), (date(2026, 10, 15), 1),
    (date(2026, 12, 1), 1),
])
def test_seasonal_cuts_per_group(d, cuts):
    assert seasonal_cuts_per_group(d) == cuts
