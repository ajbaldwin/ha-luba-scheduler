"""Push notifications and the mowing-log calendar. Best-effort, always (review M3).

A failed notify or calendar write is logged and swallowed: it never aborts the
intent that sent it. In shadow mode both are logged no-ops.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from . import audit
from . import const as c

_LOGGER = logging.getLogger(__name__)
TAG_STATUS = "mower_status"
TAG_PROMPT = "mower_prompt"


class Notifier:
    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        self._hass = hass
        self._co = coordinator
        self.sent: list[dict[str, Any]] = []       # what was (or would be) sent

    @property
    def _shadow(self) -> bool:
        return self._co.opts.get(c.CONF_MODE, c.MODE_SHADOW) != c.MODE_ACTIVE

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self.sent.append({"service": f"{domain}.{service}", **data})
        if self._shadow:
            audit.log(self._hass, f"shadow: would call {domain}.{service} {data}")
            return
        try:
            await self._hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # noqa: BLE001 — best-effort by design
            _LOGGER.warning("Luba %s.%s failed: %s", domain, service, err)

    async def notify(self, title: str | None, message: str, tag: str = TAG_STATUS,
                     actions: list[dict[str, str]] | None = None) -> None:
        target = self._co.opts.get(c.CONF_NOTIFY)
        if not target:
            return
        extra: dict[str, Any] = {"tag": tag}
        if actions:
            extra["actions"] = actions
        data: dict[str, Any] = {"message": message, "data": extra}
        if title:
            data["title"] = title
        domain, _, service = target.partition(".")
        await self._call(domain, service, data)

    async def clear(self, tag: str = TAG_PROMPT) -> None:
        await self.notify(None, "clear_notification", tag)

    async def calendar(self, summary: str, description: str, start: datetime,
                       end: datetime) -> None:
        entity_id = self._co.opts.get(c.CONF_CALENDAR)
        if not entity_id:
            return
        await self._call("calendar", "create_event", {
            "entity_id": entity_id, "summary": summary, "description": description,
            "start_date_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date_time": end.strftime("%Y-%m-%d %H:%M:%S")})
