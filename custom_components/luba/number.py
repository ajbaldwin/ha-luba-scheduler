"""Cutting height (owner-set; rotation writes it from P2)."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import HEIGHT_MAX_MM, HEIGHT_MIN_MM
from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    async_add_entities([CuttingHeight(entry.runtime_data)])


class CuttingHeight(LubaEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_native_min_value = HEIGHT_MIN_MM
    _attr_native_max_value = HEIGHT_MAX_MM
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "cutting_height", "number")

    @property
    def native_value(self) -> int:
        return self.coordinator.store.settings.cutting_height

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.async_update_settings(cutting_height=int(value))
