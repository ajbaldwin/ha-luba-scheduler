"""Read-only coupling to the Mammotion integration: find, bind and check its entities.

No imports from ``custom_components.mammotion`` or ``pymammotion``: their
internals are not an API (0.6.4 → 0.6.9 inside six weeks). Everything here goes
through Home Assistant's registries and service table.

Binding rule (spike 2026-09-28 §1): Mammotion entities are stored by their
**entity-registry entry id**. That id survives entity_id re-slugs and the
integration's in-place unique_id re-key when an area is re-hashed under the same
name. A zone the mower rebuilt (new hash AND new name) is a new entity; its old
binding stops resolving and a repair issue asks the owner to re-pick it.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (AREA_TRANSLATION_KEY, BIND_HASH, BIND_ID, BIND_NAME, BIND_UID,
                    MAMMOTION, MOWER_ROLES, TASK_AREA_SUFFIX)

# mammotion.start_mow's fields as of Mammotion 0.6.9-beta1 (lawn_mower.py
# START_MOW_SCHEMA). Every one is sent explicitly by the commander, because an
# omitted optional key is filled with the schema default and written over the
# mower's settings (defect 22). A field outside this set means Mammotion added
# one whose default we never chose; a pinned field missing means a start would
# fail validation. Either is a repair issue.
START_MOW_FIELDS = frozenset({
    "areas", "blade_height", "border_mode", "channel_mode", "channel_width",
    "collect_grass_frequency", "is_dump", "is_edge", "is_mow", "job_id", "job_version",
    "modify", "mowing_laps", "obstacle_laps", "plan_only", "rain_tactics", "speed",
    "start_progress", "toward", "toward_included_angle", "toward_mode", "ultra_wave",
})
# Keys HA adds around every entity service schema (targets, and Remove("metadata")).
_TARGET_KEYS = frozenset({"entity_id", "device_id", "area_id", "floor_id", "label_id",
                          "metadata"})


def unique_name(hass: HomeAssistant, device_id: str) -> str | None:
    """The Mammotion device name every unique_id on the device is prefixed with."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain == MAMMOTION:
            return ident
    return None


def _device_entries(hass: HomeAssistant, device_id: str) -> list[er.RegistryEntry]:
    return [e for e in er.async_entries_for_device(er.async_get(hass), device_id,
                                                   include_disabled_entities=True)
            if e.platform == MAMMOTION]


def derive_roles(hass: HomeAssistant, device_id: str) -> tuple[dict[str, str], list[str]]:
    """Map each mower role to a registry entry id. Returns (roles, missing_roles).

    Matches domain + unique_id == f"{unique_name}_{key}". translation_key alone is
    ambiguous: lawn_mower and charging have none, "area" is shared by a sensor
    and every area switch, and "blade_height" names both a sensor and a number.
    """
    name = unique_name(hass, device_id)
    entries = _device_entries(hass, device_id)
    roles, missing = {}, []
    for role, (domain, key) in MOWER_ROLES.items():
        match = next((e for e in entries if e.domain == domain
                      and e.unique_id == f"{name}_{key}"), None)
        if match is None:
            missing.append(role)
        else:
            roles[role] = match.id
    return roles, missing


def area_switches(hass: HomeAssistant, device_id: str) -> list[er.RegistryEntry]:
    """The device's zone switches (translation_key "area", domain switch)."""
    return sorted((e for e in _device_entries(hass, device_id)
                   if e.domain == "switch" and e.translation_key == AREA_TRANSLATION_KEY),
                  key=lambda e: e.entity_id)


def binding_for(hass: HomeAssistant, entry: er.RegistryEntry) -> dict[str, Any]:
    """A zone binding: the registry id that resolves, plus a diagnostic fingerprint."""
    name = unique_name(hass, entry.device_id) if entry.device_id else None
    suffix = entry.unique_id.removeprefix(f"{name}_") if name else entry.unique_id
    return {BIND_ID: entry.id, BIND_UID: entry.unique_id, BIND_HASH: suffix,
            BIND_NAME: entry.original_name or entry.name or entry.entity_id}


def resolve(hass: HomeAssistant, registry_id: str | None) -> str | None:
    """Current entity_id for a stored registry entry id, or None if it is gone."""
    if not registry_id:
        return None
    entry = er.async_get(hass).async_get(registry_id)
    return entry.entity_id if entry else None


def task_area_sensor(hass: HomeAssistant, switch_registry_id: str) -> str | None:
    """The live task-area sensor for a bound zone switch, if the mower's job has one.

    Task-area sensors are deleted from the registry whenever their zone leaves the
    job, so they are never stored — derived at call time from the switch's
    unique_id (``<switch uid>_task_area``).
    """
    reg = er.async_get(hass)
    switch = reg.async_get(switch_registry_id)
    if switch is None:
        return None
    return reg.async_get_entity_id("sensor", MAMMOTION, f"{switch.unique_id}{TASK_AREA_SUFFIX}")


def dead_bindings(hass: HomeAssistant, ids: Iterable[str]) -> list[str]:
    """The stored registry ids that no longer resolve."""
    return [i for i in ids if resolve(hass, i) is None]


def _schema_keys(schema: Any) -> set[str] | None:
    """Field names of a wrapped service schema, or None.

    HA's wrapping has changed between releases: 2026.2 registers
    ``vol.All(vol.Schema({...}), check)``; 2026.9 wraps that again in an
    outer ``vol.Schema``. Descend through both until the field dict appears.
    """
    if isinstance(schema, dict):
        return {str(k.schema if isinstance(k, vol.Marker) else k) for k in schema}
    if isinstance(schema, vol.Schema):
        return _schema_keys(schema.schema)
    for inner in getattr(schema, "validators", ()):
        keys = _schema_keys(inner)
        if keys is not None:
            return keys
    return None


def start_mow_drift(hass: HomeAssistant) -> tuple[str, set[str], set[str]]:
    """Compare mammotion.start_mow's registered schema with the pinned field set.

    Returns (status, added, removed): status is "ok", "drift", "unreadable", or
    "absent" (the service isn't registered — Mammotion not loaded yet).
    """
    service = hass.services.async_services_for_domain(MAMMOTION).get("start_mow")
    if service is None:
        return "absent", set(), set()
    keys = _schema_keys(service.schema)
    if keys is None:
        return "unreadable", set(), set()
    fields = keys - _TARGET_KEYS
    added, removed = fields - START_MOW_FIELDS, START_MOW_FIELDS - fields
    return ("drift" if added or removed else "ok"), added, removed
