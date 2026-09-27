"""MowerCommander: the ONLY module that calls mower services (design Q5/Q6).

A test asserts no other module names ``mammotion.`` or ``lawn_mower.``
services. Every start and resume re-reads the gate and the adverse sensor
immediately before the call — including every retry (review H1, M1). There
is no parameter to skip either check.

In shadow mode every call is a logged no-op that reports success, so the
integration can make and log the same decisions as the YAML package without
ever commanding the mower. Active mode is also refused while any YAML
``automation.luba_*`` is still on: exactly one system may command the mower.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from . import audit
from . import const as c
from .mammotion import resolve, start_mow_drift

_LOGGER = logging.getLogger(__name__)
ISSUE_YAML_ACTIVE = "yaml_still_active"

# The job parameters Luba fixes on every fresh start. Every field of
# mammotion.start_mow is sent explicitly (defect 22: an omitted optional key
# is filled with the schema default and written over the mower's settings).
FIXED_JOB = {
    "speed": 0.213,               # 0.7 ft/s; the schema floor is 0.2 m/s
    "border_mode": 0,             # MowOrder.border_first
    "mowing_laps": 1,             # PERIMETER laps (BorderPatrolMode) — naming trap
    "obstacle_laps": 1,           # laps around no-go areas
    "channel_mode": 0,            # CuttingMode.single_grid
    "ultra_wave": 10,             # DetectionStrategy.no_touch
    "rain_tactics": 0,            # Luba owns rain handling (adverse abort)
    "toward_included_angle": 0,   # second-pass angle; unused in single_grid
    "start_progress": 0,          # a fresh start begins at 0
    # The six below were never sent by the YAML, so the schema defaults applied
    # on every start. Pinned to those same values: explicit, and unchanged.
    "is_mow": True,
    "is_dump": True,
    "is_edge": False,
    "collect_grass_frequency": 10,
    "job_version": 0,
    "job_id": 0,
    "modify": False,
    "plan_only": False,
}


def yaml_automations_on(hass: HomeAssistant) -> list[str]:
    """The YAML package's automations that are still on. Any one blocks active mode."""
    return sorted(s.entity_id for s in hass.states.async_all("automation")
                  if s.entity_id.startswith("automation.luba_") and s.state == STATE_ON)


class CommandRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MowerCommander:
    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        self._hass = hass
        self._co = coordinator
        self.calls: list[tuple[str, dict[str, Any]]] = []     # what was (or would be) sent

    @property
    def _opts(self) -> dict[str, Any]:
        return self._co.opts

    @property
    def shadow(self) -> bool:
        return self._opts.get(c.CONF_MODE, c.MODE_SHADOW) != c.MODE_ACTIVE

    # ---- safety reads ------------------------------------------------------------

    def gate_closed(self) -> bool:
        """Unavailable/unknown always counts as OPEN (fail closed), whatever the polarity."""
        entity_id = self._opts.get(c.CONF_GATE)
        st = self._hass.states.get(entity_id) if entity_id else None
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        on = st.state == STATE_ON
        return on if self._opts.get(c.CONF_GATE_POLARITY) == c.GATE_ON_CLOSED else not on

    def adverse_now(self) -> bool:
        return self._co.recompute().adverse

    def _check_can_command(self) -> None:
        if self.shadow:
            return
        yaml_on = yaml_automations_on(self._hass)
        if yaml_on:
            ir.async_create_issue(self._hass, c.DOMAIN, ISSUE_YAML_ACTIVE, is_fixable=False,
                                  severity=ir.IssueSeverity.CRITICAL,
                                  translation_key=ISSUE_YAML_ACTIVE,
                                  translation_placeholders={"count": str(len(yaml_on))})
            raise CommandRefused(f"{len(yaml_on)} YAML Luba automations are still on")
        ir.async_delete_issue(self._hass, c.DOMAIN, ISSUE_YAML_ACTIVE)

    def _check_safe_to_start(self) -> None:
        if not self.gate_closed():
            raise CommandRefused("gate open")
        if self.adverse_now():
            raise CommandRefused("adverse conditions")

    # ---- calls ---------------------------------------------------------------------

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self.calls.append((f"{domain}.{service}", data))
        if self.shadow:
            audit.log(self._hass, f"shadow: would call {domain}.{service} {data}")
            return
        await self._hass.services.async_call(domain, service, data, blocking=True)

    def _mower_entity(self) -> str:
        entity_id = resolve(self._hass, self._opts.get(c.CONF_ROLES, {}).get(c.ROLE_MOWER))
        if not entity_id:
            raise CommandRefused("mower entity not found (see repairs)")
        return entity_id

    async def start(self, areas: list[str], *, blade_height: int, channel_width: int,
                    toward: int, toward_mode: int) -> None:
        """A fresh, parameterised start. Raises CommandRefused; service errors propagate."""
        self._check_can_command()
        self._check_safe_to_start()
        status, added, removed = start_mow_drift(self._hass)
        if status != "ok" and not self.shadow:
            raise CommandRefused(f"mammotion.start_mow drift ({status}: +{added} -{removed})")
        data = {"device_id": self._opts[c.CONF_DEVICE], "areas": areas,
                "blade_height": blade_height, "channel_width": channel_width,
                "toward": toward, "toward_mode": toward_mode, **FIXED_JOB}
        await self._call(c.MAMMOTION, "start_mow", data)

    async def resume(self) -> None:
        """Resume a held job: the bare lawn_mower service (defect 12 — start_mow doesn't)."""
        self._check_can_command()
        self._check_safe_to_start()
        await self._call("lawn_mower", "start_mowing", {"entity_id": self._mower_entity()})

    async def dock(self) -> None:
        """Docking is always allowed — it moves the mower toward safety."""
        self._check_can_command()
        await self._call("lawn_mower", "dock", {"entity_id": self._mower_entity()})

    async def cancel_job(self) -> None:
        self._check_can_command()
        await self._call(c.MAMMOTION, "cancel_job", {"entity_id": self._mower_entity()})
