"""Luba Scheduler — schedules and supervises a Mammotion Luba mower.

Scaffold only: the config flow aborts, so no entry can be created yet and
nothing here runs. The engine arrives in later phases.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
