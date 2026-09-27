"""Window close, hard stop and next mow angle (read-only; P1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = entry.runtime_data
    async_add_entities([WindowCloseSensor(coordinator), HardStopSensor(coordinator),
                        NextAngleSensor(coordinator)])


class WindowCloseSensor(LubaEntity, SensorEntity):
    """sunset minus cutoff: after this no new run starts (in-flight runs continue)."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "window_close", "sensor")

    @property
    def native_value(self) -> datetime | None:
        return self.snap.window_close


class HardStopSensor(LubaEntity, SensorEntity):
    """Dusk: the ceiling for any run still out."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "hard_stop", "sensor")

    @property
    def native_value(self) -> datetime | None:
        return self.snap.hard_stop


class NextAngleSensor(LubaEntity, SensorEntity):
    """What the next fresh mow will be told: toward and toward_mode from one place."""
    _attr_native_unit_of_measurement = "°"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next_mow_angle", "sensor")

    @property
    def native_value(self) -> int:
        return self.snap.angle.toward

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        a = self.snap.angle
        return {"toward_mode": a.toward_mode, "out_of_range": a.out_of_range,
                "group": a.group, "plan": a.plan}
