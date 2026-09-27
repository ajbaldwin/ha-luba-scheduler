"""Conditions and readiness (read-only; P1)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = entry.runtime_data
    async_add_entities([
        OptimalSensor(coordinator), AdverseSensor(coordinator),
        GroupOkSensor(coordinator, "A"), GroupOkSensor(coordinator, "B"),
        ReadySensor(coordinator),
    ])


class _Base(LubaEntity, BinarySensorEntity):
    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key, "binary_sensor")


class OptimalSensor(_Base):
    """Permission to start: every term held for the delay. Wetness is the selected group's."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "optimal_conditions")

    @property
    def is_on(self) -> bool:
        return self.snap.optimal

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {**self.snap.optimal_terms, "group": self.snap.group or "both"}


class AdverseSensor(_Base):
    """Immediate danger. NOT the inverse of optimal."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "adverse_conditions")

    @property
    def is_on(self) -> bool:
        return self.snap.adverse

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.snap.adverse_terms)


class GroupOkSensor(_Base):
    """Conditions for one group, whichever group today is."""

    def __init__(self, coordinator, group: str) -> None:
        super().__init__(coordinator, f"group_{group.lower()}_conditions_ok")
        self._group = group

    @property
    def is_on(self) -> bool:
        return self.snap.group_ok[self._group]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {**self.snap.group_terms[self._group],
                "overseed_hold": self.snap.overseed_hold[self._group]}


class ReadySensor(_Base):
    """The mower can take a FRESH start (replaces the YAML readiness boolean)."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "ready")

    @property
    def is_on(self) -> bool:
        return self.snap.ready

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.snap.ready_terms)
