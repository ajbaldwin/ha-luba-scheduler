"""Weekly settings rotation (Monday): angle and spacing step through their lists;
cutting height and cuts-per-group follow seasonal tables. Ported verbatim from
the YAML rotate_settings (the tables are the owner's, tuned by hand).
"""
from __future__ import annotations

from datetime import date

MONTHLY_HEIGHT_MM = {1: 63, 2: 63, 3: 63, 4: 70, 5: 80, 6: 89,
                     7: 100, 8: 100, 9: 70, 10: 75, 11: 63, 12: 63}
AUGUST_BY_WEEK = {1: 100, 2: 95, 3: 85, 4: 80}          # week 5+ -> 75


def next_in(sequence: list[int], current: int | None) -> int:
    """The entry after ``current``; an unknown current restarts at the first."""
    if not sequence:
        raise ValueError("empty rotation sequence")
    idx = sequence.index(current) if current in sequence else -1
    return sequence[(idx + 1) % len(sequence)]


def seasonal_height(d: date) -> int:
    week = (d.day - 1) // 7 + 1
    base = MONTHLY_HEIGHT_MM[d.month]
    if d.month == 8:
        return AUGUST_BY_WEEK.get(week, 75)
    if d.month in (7, 9, 10, 11):
        return base
    return base - 5 if week in (1, 3) else base


def seasonal_cuts_per_group(d: date) -> int:
    m, day = d.month, d.day
    if (m == 10 and day >= 15) or m in (11, 12, 1, 2, 3) or (m == 4 and day < 15):
        return 1
    if (m == 4 and day >= 15) or m in (5, 6):
        return 3
    if m == 7:
        return 1
    if m == 8:
        return 1 if day <= 14 else 2
    return 3                                   # September, October 1-14
