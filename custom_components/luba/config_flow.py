"""Config flow for Luba Orchestrator.

Scaffold only: the user step explains that there is nothing to configure and
submitting it aborts, so an install from this build can never create an
entry, let alone command a mower.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class LubaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
        return self.async_abort(reason="not_ready")
