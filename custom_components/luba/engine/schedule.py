"""Which group mows on which weekday, and what angle the next fresh mow uses.

One function, ``group_for``, answers "which group is today" for every caller
(the scheduler and the optimal-conditions selector). The YAML package kept two
hand-synced copies of this table (review L6); this replaces both.
"""
from __future__ import annotations

from dataclasses import dataclass

# Frequency is CUTS PER GROUP per week. Weekday: Monday = 0. Groups never share
# a day, and Sunday is always free.
#   1x   A Tue            B Thu
#   2x   A Mon, Thu       B Tue, Fri
#   3x   A Mon, Wed, Fri  B Tue, Thu, Sat
SCHEDULE: dict[int, dict[int, str]] = {
    1: {1: "A", 3: "B"},
    2: {0: "A", 3: "A", 1: "B", 4: "B"},
    3: {0: "A", 2: "A", 4: "A", 1: "B", 3: "B", 5: "B"},
}

# toward_mode 1 is PathAngleSetting.absolute_angle: `toward` is a bearing from
# north. HA's UI labels 0/1/2 "Optimal/North/Random"; 0 is really
# relative_angle (defect 21). Read the enum, not the translation strings.
TOWARD_MODE_ABSOLUTE = 1


def group_for(weekday: int, freq: int) -> str:
    """The group mowing on ``weekday`` at ``freq`` cuts per group, or '' for none."""
    return SCHEDULE.get(freq, {}).get(weekday, "")


def select_group(active: str, scheduled: str, weekday: int, freq: int) -> str:
    """The group whose wetness applies right now: active → scheduled → computed.

    '' means undetermined; callers then require BOTH groups (fail safe).
    """
    for candidate in (active, scheduled, group_for(weekday, freq)):
        if candidate in ("A", "B"):
            return candidate
    return ""


@dataclass(frozen=True)
class AngleResult:
    toward: int
    toward_mode: int
    out_of_range: bool
    group: str
    plan: str


def next_angle(freq: int, group: str, cuts_done: int, angle_1: int) -> AngleResult:
    """What the NEXT fresh mow will be told: toward + toward_mode, from one place.

    Cut 2 of a 2x/3x week runs perpendicular; everything else reuses angle_1.
    More cuts than the frequency allows (e.g. an adopted manual run) is not a
    legitimate state: fall back to angle_1 and say so rather than absorb it.
    """
    done = cuts_done if group in ("A", "B") else 0
    toward = (angle_1 + 90) % 180 if done == 1 and freq >= 2 else angle_1
    out_of_range = done >= freq
    if out_of_range:
        plan = (f"Cut {done + 1} of a {freq}x week — beyond the schedule, "
                "reusing the primary angle")
    elif done == 1 and freq >= 2:
        plan = f"Group {group} cut 2 of {freq} — perpendicular"
    elif done == 2:
        plan = (f'Group {group} cut 3 of {freq} — "optimal" is unresolved, '
                "reusing the primary angle")
    else:
        plan = f"Group {group} cut 1 of {freq} — primary angle"
    return AngleResult(toward=toward, toward_mode=TOWARD_MODE_ABSOLUTE,
                       out_of_range=out_of_range, group=group, plan=plan)
