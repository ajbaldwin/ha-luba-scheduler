"""group_for / select_group / next_angle — ported from the YAML templates."""
import pytest

from custom_components.luba.engine.schedule import group_for, next_angle, select_group

# The full 3 x 7 matrix (review L6: the YAML tested 3 of 21 cells).
MATRIX = {
    1: ["", "A", "", "B", "", "", ""],
    2: ["A", "B", "", "A", "B", "", ""],
    3: ["A", "B", "A", "B", "A", "B", ""],
}


@pytest.mark.parametrize("freq", [1, 2, 3])
@pytest.mark.parametrize("weekday", range(7))
def test_group_for_matrix(freq, weekday):
    assert group_for(weekday, freq) == MATRIX[freq][weekday]


@pytest.mark.parametrize("freq", [0, 4, -1])
def test_unknown_frequency_never_mows(freq):
    assert all(group_for(d, freq) == "" for d in range(7))


def test_groups_never_share_a_day_and_sunday_is_free():
    for freq in (1, 2, 3):
        assert group_for(6, freq) == ""
        for group in "AB":
            assert sum(group_for(d, freq) == group for d in range(7)) == freq


def test_select_group_precedence():
    assert select_group("B", "A", 0, 3) == "B"          # active wins
    assert select_group("", "A", 1, 3) == "A"           # then scheduled
    assert select_group("", "", 1, 3) == "B"            # then computed (Tue @3x)
    assert select_group("unknown", "x", 6, 3) == ""     # nothing -> both groups


def test_angle_cut1_uses_primary():
    a = next_angle(3, "A", 0, 48)
    assert (a.toward, a.toward_mode, a.out_of_range) == (48, 1, False)
    assert a.plan == "Group A cut 1 of 3 — primary angle"


def test_angle_cut2_perpendicular_only_at_2x_or_more():
    assert next_angle(2, "B", 1, 48).toward == 138
    assert next_angle(3, "B", 1, 120).toward == 30          # (120 + 90) % 180
    assert next_angle(2, "B", 1, 48).plan == "Group B cut 2 of 2 — perpendicular"


def test_angle_cut3_reuses_primary():
    a = next_angle(3, "A", 2, 60)
    assert a.toward == 60 and not a.out_of_range
    assert "cut 3 of 3" in a.plan


def test_angle_beyond_schedule_is_flagged_not_absorbed():
    a = next_angle(1, "A", 1, 12)
    assert a.toward == 12 and a.out_of_range
    assert a.plan.startswith("Cut 2 of a 1x week")


def test_angle_without_group_counts_zero_cuts():
    a = next_angle(2, "", 5, 24)
    assert a.toward == 24 and not a.out_of_range
