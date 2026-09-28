"""The replay days (design Q9).

2026-09-17 is transcribed from the recorder (telemetry to the second, the
YAML's FSM path from its logbook). The four August days were purged from the
recorder (10-day retention) before P2, so they are RECONSTRUCTED from the
defect log's written timelines: the shape and the decisive values are real,
the minute-level timing is not. Each says which defect it pins.
"""
from __future__ import annotations

from custom_components.luba import const as c
from custom_components.luba.engine import fsm as F

from ..world import put
from .runner import Day, S

W, P, R, READY = c.MODE_WORKING, c.MODE_PAUSE, c.MODE_RETURNING, c.MODE_READY
CANOPY = "sensor.canopy"

# ---- 2026-09-17 (recorder) — review M7 ------------------------------------------------
# Thursday, Group B's day at 3x. Optimal stayed off all day, so the 08:45 schedule
# waited in Scheduled. HA restarted at 09:16. At 12:25 the owner started a Group B
# job from the app; the FSM adopted it. It paused for 25 s, finished at 14:38
# (progress 100), docked, and a second app job over an ungrouped zone ran
# 14:43–14:58. The FSM finalised at 15:05. The YAML logged NO calendar entry and
# counted NO cut: its adopted-run calendar event was zero-length, the calendar
# schema rejected it with vol.Invalid, and continue_on_error does not catch that,
# so log_cut stopped before the notify, latch and count, at both crossings.
DAY_0917 = Day(
    date=(2026, 9, 17), start="08:00:00", end="20:00:00", cuts_per_group=3,
    sunset="18:51:00", dusk="19:18:00",
    inputs={"binary_sensor.dry_b": "off"},
    steps=[
        S("09:16:09", "activity", "unavailable"),
        S("09:16:10", "restart", 0),
        S("09:18:51", "charging", True),
        S("09:18:52", "activity", READY),
        S("12:24:49", "task+", "Back"),
        S("12:25:43", "charging", False),
        S("12:25:43", "activity", W),
        S("12:26:05", "work_area", "path"),
        S("12:27:05", "activity", P),
        S("12:27:30", "activity", W),
        S("12:27:30", "work_area", "Back"),
        S("12:46:02", "battery", 94), S("12:46:02", "progress", 11),
        S("13:16:03", "battery", 85), S("13:16:03", "progress", 38),
        S("13:59:09", "battery", 72), S("13:59:09", "progress", 67),
        S("14:36:05", "battery", 61), S("14:36:05", "progress", 99),
        S("14:38:48", "battery", 59), S("14:38:48", "progress", 100),
        S("14:42:53", "charging", True), S("14:42:53", "task-", "Back"),
        S("14:42:53", "progress", 0), S("14:42:53", "activity", READY),
        S("14:42:53", "work_area", "Not working"),
        S("14:43:11", "battery", 60),
        S("14:43:52", "charging", False), S("14:43:52", "activity", W),
        S("14:44:13", "task+", "Slope"),
        S("14:44:14", "work_area", "path"),
        S("14:54:14", "battery", 58), S("14:54:14", "progress", 48),
        S("14:54:14", "work_area", "Slope"),
        S("14:58:42", "battery", 56), S("14:58:42", "progress", 100),
        S("14:58:42", "activity", R),
        S("14:59:03", "task-", "Slope"),
        S("15:03:29", "charging", True), S("15:03:29", "progress", 0),
        S("15:03:29", "activity", READY), S("15:03:29", "work_area", "Not working"),
        S("16:06:13", "battery", 95),
    ],
)
YAML_0917 = [("08:45:00", F.IDLE, F.SCHEDULED), ("12:25:43", F.SCHEDULED, F.RUNNING),
             ("12:27:05", F.RUNNING, F.PAUSED), ("12:27:30", F.PAUSED, F.RUNNING),
             ("14:58:42", F.RUNNING, F.RETURNING), ("15:05:29", F.RETURNING, F.COMPLETED),
             ("15:05:29", F.COMPLETED, F.IDLE)]


# ---- 2026-08-01 (reconstructed) — heat abort + unattended resume ---------------------
# An app-started Group A run adopted from a stray Scheduled; the canopy crossed
# 90 °F and adverse_abort docked it; the canopy fell, optimal's edge prompted a
# Resume, and the bare lawn_mower resume took after several attempts (defect 12:
# mammotion.start_mow does not resume a held job).
def _stray_scheduled(_world, entry) -> None:
    put(entry, state=F.SCHEDULED)


DAY_0801 = Day(
    date=(2026, 8, 1), start="10:30:00", end="21:00:00", sunset="20:10:00", dusk="20:40:00",
    setup=_stray_scheduled,
    steps=[
        S("11:00:00", "task+", "Front"), S("11:00:00", "task+", "Side"),
        S("11:00:00", "charging", False), S("11:00:00", "activity", W),
        S("12:30:00", "progress", 32), S("12:30:00", "battery", 45),
        S("13:30:00", "state", CANOPY, "92"),
        S("13:34:00", "battery", 32), S("13:34:00", "charging", True),
        S("13:34:00", "activity", P),
        S("15:10:00", "state", CANOPY, "85"),
        S("15:12:00", "ignore", "lawn_mower.start_mowing", 2),
        S("15:12:00", "tap", c.ACT_RESUME),
        S("16:30:00", "progress", 100),
        S("16:34:00", "charging", True), S("16:34:00", "activity", READY),
    ],
)


# ---- 2026-08-13 (reconstructed) — defect 25 ---------------------------------------------
# Group B's day. Started at 08:45's prompt; the canopy crossed 90 °F at 15:53 with
# the job at 61 %; it docked holding the job. The 16:14 recovery found the battery
# at 71 %. The YAML classified a docked held job as a fresh restart, applied the
# 95 % floor, and stranded the FSM in Error (the owner resumed from the app). A
# held job is a resume, at the resume floor.
DAY_0813 = Day(
    date=(2026, 8, 13), start="08:40:00", end="21:00:00", sunset="19:52:00", dusk="20:21:00",
    steps=[
        S("09:00:00", "tap", c.ACT_START),
        S("12:00:00", "progress", 40), S("12:00:00", "battery", 70),
        S("15:53:00", "progress", 61), S("15:53:00", "battery", 62),
        S("15:53:00", "state", CANOPY, "92"),
        S("15:57:00", "charging", True), S("15:57:00", "activity", P),
        S("16:14:00", "battery", 71), S("16:14:00", "state", CANOPY, "86"),
        S("16:15:00", "tap", c.ACT_RESUME),
        S("17:21:00", "progress", 100),
        S("17:25:00", "charging", True), S("17:25:00", "activity", READY),
    ],
)


# ---- 2026-08-21 (reconstructed) — carry-over + rebuilt zone (v3.1.36, defect 28) ------
# Thursday's Group A job, held docked overnight into Friday, Group B's day. The
# Group B switch had been rebuilt by the mower on 08-16 (a new entity). The YAML's
# resume validated the stamped group's switches, found B's dead, and errored; and
# its counter credited the scheduled group, so the resumed A cut never counted.
def _held_group_a_with_rebuilt_b(world, entry) -> None:
    world.hold_docked("Front", "Side", battery=100)
    put(entry, state=F.PAUSED, session__start="2026-08-20T14:00:00-07:00",
        session__active_group="A", day__scheduled_group="A",
        day__evaluated_at="2026-08-20T08:45:00-07:00")


DAY_0821 = Day(
    date=(2026, 8, 21), start="08:40:00", end="21:00:00", cuts_per_group=2,
    sunset="19:40:00", dusk="20:08:00", setup=_held_group_a_with_rebuilt_b,
    steps=[
        S("08:41:00", "rebuild", "Back"),
        S("09:00:00", "tap", c.ACT_START),
        S("11:00:00", "progress", 100),
        S("11:04:00", "charging", True), S("11:04:00", "activity", READY),
    ],
)


# ---- 2026-08-22 (reconstructed) — reboot with a slow Mammotion (v3.1.39, v3.1.42) -----
# A Saturday (no group at 2x). A morning app run of Group B completed and logged;
# at 13:09 an HA update reboot found Mammotion slow to reconnect (74 s). The
# YAML's dependency wait errored the resting Idle FSM, and close_window then
# pushed a false "No Mow Today". A resting FSM needs no hardware wait.
DAY_0822 = Day(
    date=(2026, 8, 22), start="07:00:00", end="21:00:00", cuts_per_group=2,
    sunset="19:39:00", dusk="20:07:00",
    steps=[
        S("07:30:00", "task+", "Back"), S("07:30:00", "charging", False),
        S("07:30:00", "activity", W),
        S("08:30:00", "progress", 100),
        S("08:34:00", "charging", True), S("08:34:00", "activity", READY),
        S("13:09:00", "activity", "unavailable"),
        S("13:09:00", "restart", 0),
        S("13:10:14", "activity", READY),
    ],
)
