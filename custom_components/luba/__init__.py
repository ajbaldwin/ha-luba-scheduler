"""Luba Scheduler — schedules and supervises a Mammotion Luba mower.

Installs in **shadow** mode: the orchestrator runs and logs every decision,
but mower, notify and calendar calls are no-ops, so the YAML package remains
the only system commanding the mower until cutover (design Q10).
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .commander import MowerCommander
from .coordinator import LubaCoordinator
from .dispatcher import Dispatcher
from .fsm_writer import FsmWriter
from .health import async_setup_health
from .intents import Orchestrator
from .listeners import Listeners
from .notifier import Notifier
from .store import LubaStore

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SELECT,
             Platform.SENSOR, Platform.SWITCH]

type LubaConfigEntry = ConfigEntry[LubaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LubaConfigEntry) -> bool:
    store = LubaStore(hass, entry.entry_id)
    await store.async_load()
    co = LubaCoordinator(hass, entry, store)
    await co.async_config_entry_first_refresh()
    entry.runtime_data = co

    co.fsm = FsmWriter(hass, store, on_change=co.recompute)
    co.commander = MowerCommander(hass, co)
    co.notifier = Notifier(hass, co)
    dispatcher = Dispatcher(hass, handler=lambda intent: co.orchestrator.handle(intent))
    co.dispatcher = dispatcher
    co.orchestrator = Orchestrator(hass, co, co.fsm, co.commander, co.notifier,
                                   dispatcher.dispatch)
    dispatcher.start(lambda coro, name: entry.async_create_background_task(hass, coro, name))
    entry.async_on_unload(dispatcher.stop)

    co.async_start()
    entry.async_on_unload(co.async_stop)
    listeners = Listeners(hass, co, dispatcher.dispatch, co.notifier)
    listeners.async_start()
    entry.async_on_unload(listeners.async_stop)
    entry.async_on_unload(async_setup_health(hass, entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LubaConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await LubaStore(hass, entry.entry_id).async_remove()
