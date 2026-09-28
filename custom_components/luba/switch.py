"""Auto-start: when on, a prompt that finds everything ready starts the mow itself."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    async_add_entities([AutoStart(entry.runtime_data)])


class AutoStart(LubaEntity, SwitchEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "auto_start", "switch")

    @property
    def is_on(self) -> bool:
        return self.coordinator.store.settings.auto_start

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.async_update_settings(auto_start=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.async_update_settings(auto_start=False)
