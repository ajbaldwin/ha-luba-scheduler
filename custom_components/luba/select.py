"""Owner-set mowing settings (rotation also writes these, from P2)."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CUTS_PER_GROUP_OPTIONS
from .coordinator import LubaCoordinator
from .entity import LubaEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    coordinator = entry.runtime_data
    async_add_entities([
        _IntSelect(coordinator, "cuts_per_group", "cuts_per_group",
                   lambda co: CUTS_PER_GROUP_OPTIONS, lambda co: co.store.settings.cuts_per_group),
        _IntSelect(coordinator, "angle", "angle_1",
                   lambda co: co.angle_options, lambda co: co.angle_1),
        _IntSelect(coordinator, "path_spacing", "spacing",
                   lambda co: co.spacing_options, lambda co: co.spacing),
    ])


class _IntSelect(LubaEntity, SelectEntity):
    def __init__(self, coordinator: LubaCoordinator, key: str, setting: str,
                 options: Callable[[LubaCoordinator], list[int]],
                 current: Callable[[LubaCoordinator], int]) -> None:
        super().__init__(coordinator, key, "select")
        self._setting, self._options, self._current = setting, options, current

    @property
    def options(self) -> list[str]:
        return [str(o) for o in self._options(self.coordinator)]

    @property
    def current_option(self) -> str | None:
        return str(self._current(self.coordinator))

    async def async_select_option(self, option: str) -> None:
        self.coordinator.async_update_settings(**{self._setting: int(option)})
