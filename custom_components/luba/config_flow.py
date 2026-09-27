"""Config flow for Luba Orchestrator.

Scaffold only: every attempt to add the integration aborts, so an install
from this build can never create an entry, let alone command a mower.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class LubaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_abort(reason="not_ready")
