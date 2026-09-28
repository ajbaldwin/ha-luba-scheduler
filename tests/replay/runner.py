"""Replay a real mowing day against the fake world, and record what the port did.

A day is a list of timed steps (the mower's telemetry, owner actions, inputs,
restarts). The runner moves the clock to each step — letting every timer due
in between fire, exactly as the day unfolded — applies it, and records each FSM
transition the port logs. A test compares that path with the one the YAML
package logged that day, and checks the outcomes (calendar, cut counts).

Zones use the fake mower's synthetic names: Front and Side are Group A, Back
is Group B, Slope is in neither group.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.luba import const as c

from ..common import UNIQUE
from ..world import FakeWorld, build, fire_action, local, restart, settle, tick

_TRANSITION = re.compile(r"^(?P<frm>.+?) -> (?P<to>.+?)(?: \[.*\])? corr=")


@dataclass(frozen=True)
class Step:
    at: str                     # "HH:MM:SS", local time on the day
    op: str
    args: tuple = ()


def S(at: str, op: str, *args: Any) -> Step:
    return Step(at, op, args)


@dataclass
class Day:
    date: tuple[int, int, int]
    start: str                                       # the port is loaded at this time
    end: str
    steps: list[Step]
    cuts_per_group: int = 1
    sunset: str = "19:00:00"
    dusk: str = "19:28:00"
    inputs: dict[str, str] = field(default_factory=dict)
    setup: Callable[[FakeWorld, Any], None] | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Replay:
    world: FakeWorld
    entry: Any
    transitions: list[tuple[str, str, str]]         # (HH:MM:SS, from, to)

    @property
    def path(self) -> list[tuple[str, str]]:
        return [(frm, to) for _, frm, to in self.transitions]

    def at(self, frm: str, to: str) -> str:
        return next(t for t, f, to_ in self.transitions if (f, to_) == (frm, to))

    @property
    def store(self):
        return self.entry.runtime_data.store


def _clock(day: Day, hhmmss: str) -> datetime:
    h, m, s = (int(p) for p in hhmmss.split(":"))
    return local(*day.date, h, m, s)


def _set_sun(hass: HomeAssistant, day: Day) -> None:
    hass.states.async_set("sun.sun", "above_horizon", {
        "next_setting": dt_util.as_utc(_clock(day, day.sunset)).isoformat(),
        "next_dusk": dt_util.as_utc(_clock(day, day.dusk)).isoformat()})


def _rebuild_zone(world: FakeWorld, zone: str) -> None:
    """The mower rebuilt a zone (new hash AND new name): the old entity is gone,
    a new one exists that no binding points at (the 2026-08-16 shape, spike §1)."""
    reg = er.async_get(world.hass)
    new_hash = f"9{world.zone_hash(zone)}"
    old = world.mower.zones[zone]
    reg.async_remove(old)
    world.hass.states.async_remove(old)
    entry = reg.async_get_or_create(
        "switch", c.MAMMOTION, f"{UNIQUE}_{new_hash}", device_id=world.mower.device_id,
        suggested_object_id=f"test_mower_area_{zone.lower()}_rebuilt", translation_key="area",
        original_name=f"Area {zone} rebuilt")
    world.hass.states.async_set(entry.entity_id, "off", {"hash": int(new_hash)})


async def _apply(hass: HomeAssistant, entry, freezer, world: FakeWorld, step: Step) -> None:
    op, a = step.op, step.args
    if op == "activity":
        world.set_mode(a[0])
    elif op == "charging":
        world.set_charging(a[0])
    elif op == "progress":
        world.set_progress(a[0])
    elif op == "battery":
        world.set_battery(a[0])
    elif op == "work_area":
        world.set_work_area(a[0])
    elif op == "task+":
        world.add_task_area(*a)
    elif op == "task-":
        world.remove_task_area(a[0])
    elif op == "state":
        hass.states.async_set(a[0], a[1])
    elif op == "ignore":
        world.ignore(*a)
    elif op == "tap":
        await fire_action(hass, entry, world.last_prompt_action(a[0]), freezer)
    elif op == "restart":
        await restart(hass, entry, freezer, downtime=timedelta(seconds=a[0]))
    elif op == "rebuild":
        _rebuild_zone(world, a[0])
    elif op == "dispatch":
        entry.runtime_data.dispatcher.dispatch(a[0], **(a[1] if len(a) > 1 else {}))
    else:
        raise ValueError(f"unknown replay op {op!r}")


async def replay(hass: HomeAssistant, freezer, day: Day) -> Replay:
    world, entry = await build(hass, freezer, at=_clock(day, day.start), **day.options)
    transitions: list[tuple[str, str, str]] = []

    @callback
    def _log(event) -> None:
        if not str(event.data.get("name", "")).endswith("FSM"):
            return
        if m := _TRANSITION.match(str(event.data.get("message", ""))):
            transitions.append((dt_util.now().strftime("%H:%M:%S"), m["frm"], m["to"]))

    hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, _log)
    entry.runtime_data.async_update_settings(cuts_per_group=day.cuts_per_group)
    _set_sun(hass, day)
    for entity_id, value in day.inputs.items():
        hass.states.async_set(entity_id, value)
    if day.setup:
        day.setup(world, entry)
    await settle(hass, entry, freezer)

    for step in [*day.steps, S(day.end, "noop")]:
        # A minute at a time, so every timer fires at its own time (08:45, a
        # deadline, the idle debounce), not at the next step's.
        while (delta := _clock(day, step.at) - dt_util.now()) > timedelta():
            await tick(hass, entry, freezer, min(delta, timedelta(minutes=1)))
        if step.op != "noop":
            await _apply(hass, entry, freezer, world, step)
            await settle(hass, entry, freezer)
    return Replay(world, entry, transitions)


def within(actual: str, expected: str, seconds: int = 10) -> bool:
    a, e = (datetime.strptime(t, "%H:%M:%S") for t in (actual, expected))
    return abs((a - e).total_seconds()) <= seconds
