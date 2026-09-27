"""Clear error: the dashboard twin of the notification's Clear Error action."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    async_add_entities([ClearError(entry.runtime_data)])


class ClearError(LubaEntity, ButtonEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clear_error", "button")

    async def async_press(self) -> None:
        self.coordinator.dispatcher.dispatch("clear_error")
