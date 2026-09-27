"""Luba Scheduler — schedules and supervises a Mammotion Luba mower.

P1 (read-only): conditions, readiness, window and angle entities, owner
settings, and repair checks on the Mammotion bindings. Nothing here commands
the mower, sends a notification or writes a calendar entry.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import LubaCoordinator
from .health import async_setup_health
from .store import LubaStore

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SENSOR]

type LubaConfigEntry = ConfigEntry[LubaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LubaConfigEntry) -> bool:
    store = LubaStore(hass, entry.entry_id)
    await store.async_load()
    coordinator = LubaCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
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
