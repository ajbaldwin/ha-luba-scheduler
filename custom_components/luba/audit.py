"""Logbook lines, attached to sensor.luba_state (fired directly: no logbook dependency)."""
from __future__ import annotations

from homeassistant.const import EVENT_LOGBOOK_ENTRY
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, STATE_ENTITY_ID, TITLE


@callback
def log(hass: HomeAssistant, message: str, name: str = TITLE) -> None:
    hass.bus.async_fire(EVENT_LOGBOOK_ENTRY, {
        "name": name, "message": message, "domain": DOMAIN, "entity_id": STATE_ENTITY_ID})
