"""Base entity: one service device, explicit ``luba_*`` entity ids (design Q2)."""
from __future__ import annotations

from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TITLE
from .coordinator import LubaCoordinator, Snapshot


class LubaEntity(CoordinatorEntity[LubaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LubaCoordinator, key: str, platform: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._suggested_entity_id = f"{platform}.{DOMAIN}_{key}"
        self.entity_id = self._suggested_entity_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=TITLE,
                                            manufacturer=TITLE, entry_type=DeviceEntryType.SERVICE)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # If HA had to suffix our id ("_2"), something else holds it, most likely a
        # leftover entity. Say so instead of running under a surprising id.
        issue_id = f"entity_id_taken_{self._key}"
        if self.entity_id.startswith(f"{self._suggested_entity_id}_"):
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="entity_id_taken",
                translation_placeholders={"expected": self._suggested_entity_id,
                                          "actual": self.entity_id})
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @property
    def snap(self) -> Snapshot:
        return self.coordinator.data
