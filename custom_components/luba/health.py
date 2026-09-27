"""Read-only health checks, raised as repair issues.

* **Dead bindings**: a stored Mammotion registry id that no longer resolves.
  The 2026-08-16 zone rebuild would have raised this five days before the
  resume it broke (spike §1).
* **start_mow drift**: mammotion.start_mow gained or lost a field since the
  pinned set (defect 22 / review L8).

Runs once HA has started, daily, whenever the entity registry changes, and
whenever Mammotion registers a service (it may load after us).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_SERVICE_REGISTERED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started

from .const import BIND_ID, BIND_NAME, CONF_ROLES, CONF_ZONES, DOMAIN, MAMMOTION
from .mammotion import resolve, start_mow_drift

ISSUE_DEAD = "dead_bindings"
ISSUE_DRIFT = "start_mow_drift"
ISSUE_UNREADABLE = "start_mow_unreadable"


def dead_binding_names(hass: HomeAssistant, options: dict[str, Any]) -> list[str]:
    dead = [f"mower {role}" for role, rid in options.get(CONF_ROLES, {}).items()
            if resolve(hass, rid) is None]
    for group, bindings in sorted(options.get(CONF_ZONES, {}).items()):
        dead += [f"Group {group} zone {b.get(BIND_NAME, '?')}" for b in bindings
                 if resolve(hass, b.get(BIND_ID)) is None]
    return dead


def _issue(hass: HomeAssistant, issue_id: str, placeholders: dict[str, str]) -> None:
    ir.async_create_issue(hass, DOMAIN, issue_id, is_fixable=False,
                          severity=ir.IssueSeverity.ERROR, translation_key=issue_id,
                          translation_placeholders=placeholders)


@callback
def async_run_checks(hass: HomeAssistant, entry: ConfigEntry) -> None:
    dead = dead_binding_names(hass, dict(entry.options))
    if dead:
        _issue(hass, ISSUE_DEAD, {"names": ", ".join(dead)})
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_DEAD)

    status, added, removed = start_mow_drift(hass)
    if status == "absent":
        return                      # Mammotion not loaded (yet): re-checked on registration
    if status == "unreadable":
        _issue(hass, ISSUE_UNREADABLE, {})
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_UNREADABLE)
    if status == "drift":
        _issue(hass, ISSUE_DRIFT, {"added": ", ".join(sorted(added)) or "none",
                                   "removed": ", ".join(sorted(removed)) or "none"})
    elif status == "ok":
        ir.async_delete_issue(hass, DOMAIN, ISSUE_DRIFT)


@callback
def async_setup_health(hass: HomeAssistant, entry: ConfigEntry) -> Callable[[], None]:
    @callback
    def _run(*_: Any) -> None:
        async_run_checks(hass, entry)

    @callback
    def _is_mammotion(data: dict[str, Any]) -> bool:
        return data.get("domain") == MAMMOTION

    unsubs = [
        async_at_started(hass, _run),
        async_track_time_interval(hass, _run, timedelta(days=1)),
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _run),
        hass.bus.async_listen(EVENT_SERVICE_REGISTERED, _run, event_filter=_is_mammotion),
    ]

    @callback
    def _unsub() -> None:
        for unsub in unsubs:
            unsub()
    return _unsub
