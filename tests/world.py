"""A fake world for engine tests: the mower's services, a phone and a calendar.

``FakeWorld`` registers ``mammotion.start_mow`` / ``cancel_job`` and
``lawn_mower.start_mowing`` / ``dock``, plus ``notify.test_phone`` and
``calendar.create_event``. Every call is recorded. Each mower service has a
default reaction that moves the fake mower the way the real one does (activity
mode, task-area sensors, charging); a test overrides the next N reactions with
``world.react(service, fn)`` / ``world.ignore(service)`` to script a scenario
("the first start is ignored and the gate opens meanwhile").

Synthetic identifiers only, like ``common.py``.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.luba import const as c
from custom_components.luba.mammotion import START_MOW_FIELDS

from .common import UNIQUE, FakeMower, add_mower, set_good_day, setup_luba

NOTIFY = "notify.test_phone"
CALENDAR = "calendar.mow_log"
MOWER_SERVICES = ("mammotion.start_mow", "mammotion.cancel_job",
                  "lawn_mower.start_mowing", "lawn_mower.dock")

Reaction = Callable[["FakeWorld", dict[str, Any]], None]


def local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=dt_util.get_default_time_zone())


class FakeWorld:
    def __init__(self, hass: HomeAssistant, mower: FakeMower) -> None:
        self.hass = hass
        self.mower = mower
        self.calls: list[tuple[str, dict[str, Any]]] = []       # mower services only
        self.notifications: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._scripted: dict[str, list[Reaction]] = {s: [] for s in MOWER_SERVICES}
        self.task_areas: dict[str, str] = {}                     # hash -> sensor entity_id
        for name, entity_id in mower.zones.items():
            self.hass.states.async_set(entity_id, "off",
                                       {"hash": int(self.zone_hash(name))})

    # ---- installation --------------------------------------------------------------

    def install(self) -> FakeWorld:
        start_schema = cv.make_entity_service_schema(
            {vol.Optional(f): object for f in START_MOW_FIELDS})
        plain = cv.make_entity_service_schema({})
        for full, schema in (("mammotion.start_mow", start_schema),
                             ("mammotion.cancel_job", plain),
                             ("lawn_mower.start_mowing", plain), ("lawn_mower.dock", plain)):
            domain, service = full.split(".")
            self.hass.services.async_register(domain, service, self._mower_handler(full),
                                              schema=schema)
        self.hass.services.async_register("notify", "test_phone", self._on_notify)
        self.hass.services.async_register("calendar", "create_event", self._on_calendar)
        return self

    def _mower_handler(self, full: str):
        async def _handle(call: ServiceCall) -> None:
            data = dict(call.data)
            self.calls.append((full, data))
            scripted = self._scripted[full]
            reaction = scripted.pop(0) if scripted else _DEFAULTS[full]
            reaction(self, data)
        return _handle

    async def _on_notify(self, call: ServiceCall) -> None:
        self.notifications.append(dict(call.data))

    async def _on_calendar(self, call: ServiceCall) -> None:
        self.events.append(dict(call.data))

    def follow_shadow(self, entry) -> None:
        """Shadow scenarios: the YAML package, deciding the same, runs each command Luba logs.

        Luba's commander records a would-be call and logs "shadow: would call …";
        the fake mower then reacts as if the YAML had sent it. Nothing is recorded
        in ``self.calls`` — no real service was called.
        """
        commander = entry.runtime_data.commander

        @callback
        def _on_log(event) -> None:
            message = str(event.data.get("message", ""))
            if not message.startswith("shadow: would call "):
                return
            service = message.removeprefix("shadow: would call ").split(" ", 1)[0]
            if service in _DEFAULTS:                  # a mower command, not a notify
                name, data = commander.calls[-1]
                assert name == service
                _DEFAULTS[name](self, data)

        self.hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, _on_log)

    # ---- scripting -----------------------------------------------------------------

    def react(self, service: str, fn: Reaction, times: int = 1) -> None:
        """Replace the default reaction for the next ``times`` calls of ``service``."""
        self._scripted[service].extend([fn] * times)

    def ignore(self, service: str, times: int = 1) -> None:
        self.react(service, lambda _w, _d: None, times)

    def called(self, service: str) -> list[dict[str, Any]]:
        return [data for name, data in self.calls if name == service]

    def prompts(self) -> list[dict[str, Any]]:
        """Actionable prompts sent (a notification carrying buttons)."""
        return [n for n in self.notifications if n.get("data", {}).get("actions")
                and n["data"].get("tag") == "mower_prompt"]

    def last_prompt_action(self, prefix: str) -> str:
        for n in reversed(self.prompts()):
            for action in n["data"]["actions"]:
                if action["action"].startswith(prefix):
                    return action["action"]
        raise AssertionError(f"no prompt offered {prefix}")

    # ---- the fake mower ------------------------------------------------------------

    def zone_hash(self, name: str) -> str:
        entry = er.async_get(self.hass).async_get(self.mower.zones[name])
        return entry.unique_id.removeprefix(f"{UNIQUE}_")

    def _role(self, role: str) -> str:
        return self.mower.roles[role]

    @property
    def mode(self) -> str | None:
        st = self.hass.states.get(self._role(c.ROLE_ACTIVITY))
        return st.state if st else None

    def set_mode(self, mode: str) -> None:
        """Activity mode, and the lawn_mower entity's matching state (as Mammotion reports it)."""
        self.hass.states.async_set(self._role(c.ROLE_ACTIVITY), mode)
        self.hass.states.async_set(self._role(c.ROLE_MOWER), _LAWN_MOWER.get(mode, "docked"))

    def set_battery(self, pct: float) -> None:
        self.hass.states.async_set(self._role(c.ROLE_BATTERY), str(pct))

    def set_charging(self, on: bool) -> None:
        self.hass.states.async_set(self._role(c.ROLE_CHARGING), "on" if on else "off")

    def set_progress(self, pct: float) -> None:
        self.hass.states.async_set(self._role(c.ROLE_PROGRESS), str(pct))

    def set_work_area(self, name: str) -> None:
        self.hass.states.async_set(self._role(c.ROLE_WORK_AREA), name)

    def start_job(self, hashes: list[str]) -> None:
        """Mammotion creates a task-area sensor per zone in the job (and removes the rest)."""
        self.clear_job()
        reg = er.async_get(self.hass)
        for zone_hash in hashes:
            entry = reg.async_get_or_create(
                "sensor", c.MAMMOTION, f"{UNIQUE}_{zone_hash}{c.TASK_AREA_SUFFIX}",
                device_id=self.mower.device_id, suggested_object_id=f"test_task_area_{zone_hash}")
            self.hass.states.async_set(entry.entity_id, "0")
            self.task_areas[zone_hash] = entry.entity_id

    def start_job_for(self, *zones: str) -> None:
        self.start_job([self.zone_hash(z) for z in zones])

    def clear_job(self) -> None:
        reg = er.async_get(self.hass)
        for entity_id in self.task_areas.values():
            reg.async_remove(entity_id)
            self.hass.states.async_remove(entity_id)
        self.task_areas.clear()

    def reslug(self, name: str, new_entity_id: str) -> None:
        """The integration renames a zone switch's entity_id (the registry entry id survives)."""
        old = self.mower.zones[name]
        st = self.hass.states.get(old)
        er.async_get(self.hass).async_update_entity(old, new_entity_id=new_entity_id)
        self.hass.states.async_remove(old)
        self.hass.states.async_set(new_entity_id, st.state, st.attributes)
        self.mower.zones[name] = new_entity_id

    def open_gate(self, is_open: bool = True) -> None:
        self.hass.states.async_set("binary_sensor.gate_closed", "off" if is_open else "on")

    def rain(self, raining: bool = True) -> None:
        self.hass.states.async_set("sensor.precip_type", "rain" if raining else "none")

    def mow_manually(self, *zones: str) -> None:
        """The owner starts a job from the Mammotion app: it leaves the dock and works."""
        self.start_job_for(*zones)
        self.set_charging(False)
        self.set_mode(c.MODE_WORKING)

    def hold_docked(self, *zones: str, battery: float = 60) -> None:
        """A held job, docked and charging (the carry-over / weather-abort shape)."""
        if zones:
            self.start_job_for(*zones)
        self.set_battery(battery)
        self.set_charging(True)
        self.set_mode(c.MODE_PAUSE)

    def finish(self) -> None:
        """The job completes: progress crosses 100, then the mower reports ready."""
        self.set_progress(100)
        self.set_charging(True)
        self.set_mode(c.MODE_READY)


def _start_mow(world: FakeWorld, data: dict[str, Any]) -> None:
    hashes = []
    for entity_id in data.get("areas", []):
        st = world.hass.states.get(entity_id)
        if st is not None and st.attributes.get("hash") is not None:
            hashes.append(str(st.attributes["hash"]))
    world.start_job(hashes)
    world.set_progress(0)
    world.set_charging(False)
    world.set_mode(c.MODE_WORKING)


def _resume(world: FakeWorld, _data: dict[str, Any]) -> None:
    world.set_charging(False)
    world.set_mode(c.MODE_WORKING)


def _dock(world: FakeWorld, _data: dict[str, Any]) -> None:
    world.set_mode(c.MODE_RETURNING)


def _cancel(world: FakeWorld, _data: dict[str, Any]) -> None:
    world.clear_job()
    world.set_mode(c.MODE_READY)


_LAWN_MOWER = {c.MODE_WORKING: "mowing", c.MODE_PAUSE: "paused", c.MODE_PAUSED: "paused",
               c.MODE_RETURNING: "returning"}

_DEFAULTS: dict[str, Reaction] = {
    "mammotion.start_mow": _start_mow, "mammotion.cancel_job": _cancel,
    "lawn_mower.start_mowing": _resume, "lawn_mower.dock": _dock,
}

# Test options: no delay_on (a scenario ticks time explicitly where it matters),
# and the fake phone and calendar as targets. Every other timing is the default.
FAST = {c.CONF_OPTIMAL_DELAY: 0, c.CONF_NOTIFY: NOTIFY, c.CONF_CALENDAR: CALENDAR}
STEP = timedelta(seconds=1)


async def settle(hass: HomeAssistant, entry, freezer=None, limit: timedelta = timedelta(hours=1)) -> None:
    """Run until no intent is queued or running.

    An intent waiting on the mower (start verification, a dock, a cancel) waits on
    HA time; with ``freezer`` given, the clock advances a second at a time until it
    finishes, as it would in real life. Without it, a waiting intent fails the test.
    """
    dispatcher = entry.runtime_data.dispatcher
    elapsed = timedelta()
    while True:
        for _ in range(3):
            await hass.async_block_till_done()
        if dispatcher.idle:
            return
        if freezer is None or elapsed >= limit:
            raise AssertionError(f"intents still running after {elapsed}: "
                                 f"{dispatcher.handled[-3:]}")
        freezer.tick(STEP)
        elapsed += STEP
        async_fire_time_changed(hass)


async def tick(hass: HomeAssistant, entry, freezer, delta: timedelta) -> None:
    """Let pending state changes land (listeners arm their timers now), then jump the clock."""
    await settle(hass, entry, freezer)
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await settle(hass, entry, freezer)


async def build(hass: HomeAssistant, freezer, *, at: datetime | None = None,
                active: bool = True, **overrides) -> tuple[FakeWorld, Any]:
    """A fake mower on a good day, a fake world, and a loaded Luba entry."""
    freezer.move_to(at or local(2026, 9, 29, 8, 40))          # a Tuesday: Group A at 1x
    mower = add_mower(hass)
    set_good_day(hass, mower)
    world = FakeWorld(hass, mower).install()
    world.set_mode(c.MODE_READY)
    world.set_charging(True)
    world.set_progress(0)
    world.set_work_area("Not working")
    options = {**FAST, c.CONF_MODE: c.MODE_ACTIVE if active else c.MODE_SHADOW, **overrides}
    entry = await setup_luba(hass, mower, **options)
    await settle(hass, entry, freezer)
    return world, entry


def fsm(entry) -> str:
    return entry.runtime_data.store.fsm.state


async def fire_action(hass: HomeAssistant, entry, action: str, freezer=None) -> None:
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await settle(hass, entry, freezer)


async def dispatch(hass: HomeAssistant, entry, *intents: str | tuple[str, dict],
                   freezer=None) -> None:
    """Enqueue intents back to back (the same instant), then settle."""
    for item in intents:
        name, ctx = (item, {}) if isinstance(item, str) else item
        entry.runtime_data.dispatcher.dispatch(name, **ctx)
    await settle(hass, entry, freezer)


def jump(freezer, delta: timedelta) -> None:
    """Move the clock WITHOUT firing timers (the state a test wants to act in)."""
    freezer.tick(delta)


def later(hours: float = 0, minutes: float = 0) -> timedelta:
    return timedelta(hours=hours, minutes=minutes)


def put(entry, *, state: str | None = None, **fields) -> None:
    """Test-only: place the store in a given shape (as if earlier days had happened).

    Keys are ``section__field`` (``session__start=...``, ``day__scheduled_group="A"``).
    """
    store = entry.runtime_data.store
    if state is not None:
        store.fsm.state = state
    for key, value in fields.items():
        section, name = key.split("__")
        setattr(getattr(store, section), name, value)
    entry.runtime_data.recompute()


async def restart(hass: HomeAssistant, entry, freezer, downtime: timedelta = timedelta()) -> None:
    """Unload the entry (store saved), let ``downtime`` pass, load it again."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    if downtime:
        freezer.tick(downtime)
        async_fire_time_changed(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass, entry, freezer)
