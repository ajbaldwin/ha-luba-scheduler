"""FSM state, cut counters, window close, hard stop and next mow angle."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import const as c
from .engine.fsm import STATES
from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = entry.runtime_data
    async_add_entities([StateSensor(coordinator), CutsSensor(coordinator, "A"),
                        CutsSensor(coordinator, "B"), WindowCloseSensor(coordinator),
                        HardStopSensor(coordinator), NextAngleSensor(coordinator)])


class StateSensor(LubaEntity, SensorEntity):
    """The FSM. Read-only: nothing outside the FSM writer can change it (no service)."""
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATES)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "state", "sensor")

    @property
    def native_value(self) -> str:
        return self.coordinator.store.fsm.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.store
        return {
            "mode": self.coordinator.opts.get(c.CONF_MODE, c.MODE_SHADOW),
            "prior_state": s.fsm.prior_state, "error_from": s.fsm.error_from,
            "last_transition_at": s.fsm.last_transition_at, "last_corr": s.fsm.last_corr,
            "scheduled_group": s.day.scheduled_group, "active_group": s.session.active_group,
            "session_start": s.session.start, "session_battery_start": s.session.battery_start,
            "session_work_area": s.session.work_area, "abort_reason": s.session.abort_reason,
            "ack_deadline": s.day.ack_deadline,
        }


class CutsSensor(LubaEntity, SensorEntity):
    """Cuts completed this week for one group (reset by the Monday rotation)."""

    def __init__(self, coordinator, group: str) -> None:
        super().__init__(coordinator, f"group_{group.lower()}_cuts", "sensor")
        self._group = group

    @property
    def native_value(self) -> int:
        return self.coordinator.store.counters.cuts.get(self._group, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        counters = self.coordinator.store.counters
        return {"last_counted_cut": counters.last_counted_cut,
                "last_logged_cut": counters.last_logged_cut, "week_of": counters.week_of}


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
