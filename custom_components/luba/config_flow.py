"""Config flow: mower → zones → condition inputs → gate. Options flow re-edits each.

Mammotion entities are bound by entity-registry entry id (see mammotion.py);
everything else is an ordinary entity_id the owner picks.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    DeviceSelector, DeviceSelectorConfig, EntityFilterSelectorConfig, EntitySelector,
    EntitySelectorConfig, NumberSelector, NumberSelectorConfig, NumberSelectorMode,
    BooleanSelector, SelectSelector, SelectSelectorConfig, SelectSelectorMode, TextSelector,
    TimeSelector)

from . import const as c
from .commander import yaml_automations_on
from .mammotion import area_switches, binding_for, derive_roles


def _suggest(value: Any) -> dict:
    return {"suggested_value": value}


def _clean(user_input: dict) -> dict:
    return {k: v for k, v in user_input.items() if v not in (None, "", [])}


def _entity(domain: str | list[str], **kw: Any) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain, **kw))


def _number(lo: float, hi: float, step: float = 1, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=lo, max=hi, step=step, mode=NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _notify_choices(hass: HomeAssistant, current: str | None) -> list[str]:
    choices = {f"notify.{n}" for n in hass.services.async_services_for_domain("notify")
               if n != "send_message"}
    if current:
        choices.add(current)
    return sorted(choices)


# ---- mower -----------------------------------------------------------------------

def _mower_schema(values: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(c.CONF_DEVICE, default=values.get(c.CONF_DEVICE, vol.UNDEFINED)):
            DeviceSelector(DeviceSelectorConfig(
                integration=c.MAMMOTION, entity=[EntityFilterSelectorConfig(domain="lawn_mower")])),
    })


def _validate_mower(hass: HomeAssistant, device_id: str) -> tuple[dict, dict, dict]:
    """Returns (options_update, errors, placeholders)."""
    roles, missing = derive_roles(hass, device_id)
    if missing:
        return {}, {"base": "missing_roles"}, {"missing": ", ".join(missing)}
    if not area_switches(hass, device_id):
        return {}, {"base": "no_zones"}, {}
    return {c.CONF_DEVICE: device_id, c.CONF_ROLES: roles}, {}, {}


# ---- zones -----------------------------------------------------------------------

def _zones_schema(hass: HomeAssistant, device_id: str, values: dict) -> vol.Schema:
    switches = [e.entity_id for e in area_switches(hass, device_id)]
    reg = er.async_get(hass)
    current = {}
    for group in c.GROUPS:
        ids = [reg.async_get(b[c.BIND_ID]) for b in values.get(c.CONF_ZONES, {}).get(group, [])]
        current[group] = [e.entity_id for e in ids if e is not None]
    selector = _entity("switch", multiple=True, include_entities=switches)
    return vol.Schema({
        vol.Required(f"group_{g.lower()}", default=current[g]): selector for g in c.GROUPS
    })


def _validate_zones(hass: HomeAssistant, user_input: dict) -> tuple[dict, dict]:
    picked = {g: user_input.get(f"group_{g.lower()}", []) for g in c.GROUPS}
    if not all(picked.values()):
        return {}, {"base": "empty_group"}
    if set(picked["A"]) & set(picked["B"]):
        return {}, {"base": "overlapping_groups"}
    reg = er.async_get(hass)
    zones = {g: [binding_for(hass, reg.async_get(eid)) for eid in picked[g]] for g in c.GROUPS}
    return {c.CONF_ZONES: zones}, {}


# ---- inputs & gate ---------------------------------------------------------------

def _inputs_schema(hass: HomeAssistant, values: dict) -> vol.Schema:
    def req(key: str, selector) -> tuple:
        return vol.Required(key, default=values.get(key, vol.UNDEFINED)), selector

    def opt(key: str, selector) -> tuple:
        return vol.Optional(key, description=_suggest(values.get(key))), selector

    fields = [
        req(c.CONF_SEASON, _entity(["input_boolean", "switch", "binary_sensor"])),
        req(c.CONF_CANOPY, _entity("sensor")),
        req(c.CONF_PRECIP_CHANCE, _entity("sensor")),
        req(c.CONF_DRY["A"], _entity(["binary_sensor", "input_boolean"])),
        req(c.CONF_DRY["B"], _entity(["binary_sensor", "input_boolean"])),
        opt(c.CONF_WEATHER, _entity("weather")),
        opt(c.CONF_PRECIP_TYPE, _entity("sensor")),
        opt(c.CONF_LIGHTNING_DISTANCE, _entity("sensor")),
        opt(c.CONF_LIGHTNING_STRIKE, _entity("sensor")),
        opt(c.CONF_MOW_ALLOWED["A"], _entity(["binary_sensor", "input_boolean"])),
        opt(c.CONF_MOW_ALLOWED["B"], _entity(["binary_sensor", "input_boolean"])),
        opt(c.CONF_CALENDAR, _entity("calendar")),
        opt(c.CONF_NOTIFY, SelectSelector(SelectSelectorConfig(
            options=_notify_choices(hass, values.get(c.CONF_NOTIFY)),
            mode=SelectSelectorMode.DROPDOWN))),
    ]
    return vol.Schema(dict(fields))


def _gate_schema(values: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(c.CONF_GATE, default=values.get(c.CONF_GATE, vol.UNDEFINED)):
            _entity(["binary_sensor", "input_boolean", "switch"]),
        vol.Required(c.CONF_GATE_POLARITY,
                     default=values.get(c.CONF_GATE_POLARITY, c.GATE_ON_CLOSED)):
            SelectSelector(SelectSelectorConfig(options=[c.GATE_ON_CLOSED, c.GATE_ON_OPEN],
                                                translation_key="gate_polarity")),
    })


# ---- tuning (options only) ---------------------------------------------------------

def _int_list(text: str, lo: int, hi: int) -> list[int] | None:
    try:
        values = [int(p) for p in text.replace(";", ",").split(",") if p.strip()]
    except ValueError:
        return None
    if not values or len(set(values)) != len(values) or not all(lo <= v <= hi for v in values):
        return None
    return values


TUNING_NUMBERS: dict[str, tuple[float, float, str | None]] = {
    c.CONF_CUTOFF_MIN: (0, 240, "min"),
    c.CONF_CANOPY_MIN: (0, 120, "°F"),
    c.CONF_CANOPY_MAX: (0, 130, "°F"),
    c.CONF_PRECIP_MAX: (1, 100, "%"),
    c.CONF_LIGHTNING_RADIUS: (0, 100, None),
    c.CONF_LIGHTNING_RECENCY: (1, 120, "min"),
    c.CONF_START_FLOOR: (20, 100, "%"),
    c.CONF_OPTIMAL_DELAY: (0, 60, "min"),
}


def _tuning_schema(values: dict) -> vol.Schema:
    fields: dict = {
        vol.Required(key, default=values[key]): _number(lo, hi, 1, unit)
        for key, (lo, hi, unit) in TUNING_NUMBERS.items()
    }
    fields[vol.Required(c.CONF_ANGLES, default=", ".join(map(str, values[c.CONF_ANGLES])))] = \
        TextSelector()
    fields[vol.Required(c.CONF_SPACINGS, default=", ".join(map(str, values[c.CONF_SPACINGS])))] = \
        TextSelector()
    return vol.Schema(fields)


def _validate_tuning(user_input: dict) -> tuple[dict, dict]:
    out: dict[str, Any] = {key: int(user_input[key]) for key in TUNING_NUMBERS}
    errors = {}
    if out[c.CONF_CANOPY_MIN] >= out[c.CONF_CANOPY_MAX]:
        errors[c.CONF_CANOPY_MAX] = "canopy_range"
    angles = _int_list(user_input[c.CONF_ANGLES], 0, 179)
    spacings = _int_list(user_input[c.CONF_SPACINGS], 5, 35)     # start_mow channel_width
    if angles is None:
        errors[c.CONF_ANGLES] = "bad_list"
    if spacings is None:
        errors[c.CONF_SPACINGS] = "bad_list"
    out[c.CONF_ANGLES], out[c.CONF_SPACINGS] = angles, spacings
    return out, errors


# ---- timing and mode (options only) --------------------------------------------------

TIMING_NUMBERS: dict[str, tuple[float, float, str | None]] = {
    c.CONF_START_VERIFY: (10, 600, "s"),
    c.CONF_START_ATTEMPTS: (1, 10, None),
    c.CONF_ROUTE_VERIFY: (10, 600, "s"),
    c.CONF_REPROMPT: (5, 240, "min"),
    c.CONF_CANCEL_TIMEOUT: (10, 600, "s"),
    c.CONF_RESUME_FLOOR: (5, 100, "%"),
    c.CONF_OFFLINE_TIMEOUT: (1, 60, "min"),
    c.CONF_IDLE_RECONCILE: (1, 60, "min"),
}
TIMES = (c.CONF_SCHEDULER_TIME, c.CONF_ROTATION_TIME)
CONF_CONFIRM_ACTIVE = "confirm_active"


def _timing_schema(values: dict) -> vol.Schema:
    fields: dict = {vol.Required(key, default=values[key]): TimeSelector() for key in TIMES}
    fields.update({
        vol.Required(key, default=values[key]): _number(lo, hi, 1, unit)
        for key, (lo, hi, unit) in TIMING_NUMBERS.items()
    })
    return vol.Schema(fields)


def _validate_timing(user_input: dict, values: dict) -> tuple[dict, dict]:
    out: dict[str, Any] = {key: int(user_input[key]) for key in TIMING_NUMBERS}
    errors = {}
    for key in TIMES:               # TimeSelector has validated it; store HH:MM:SS
        h, m, s = (int(p) for p in (str(user_input[key]).split(":") + ["0", "0"])[:3])
        out[key] = f"{h:02d}:{m:02d}:{s:02d}"
    if out[c.CONF_RESUME_FLOOR] > values[c.CONF_START_FLOOR]:
        errors[c.CONF_RESUME_FLOOR] = "resume_above_start"
    return out, errors


def _mode_schema(values: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(c.CONF_MODE, default=values.get(c.CONF_MODE, c.MODE_SHADOW)):
            SelectSelector(SelectSelectorConfig(options=[c.MODE_SHADOW, c.MODE_ACTIVE],
                                                translation_key="mode")),
        vol.Optional(CONF_CONFIRM_ACTIVE, default=False): BooleanSelector(),
        vol.Optional(c.CONF_YAML_STATE, description=_suggest(values.get(c.CONF_YAML_STATE))):
            _entity(["input_select", "select", "sensor"]),
    })


def _validate_mode(hass: HomeAssistant, user_input: dict) -> tuple[dict, dict, dict]:
    """Returns (options_update, errors, placeholders). Shadow is always accepted."""
    extra = _clean({c.CONF_YAML_STATE: user_input.get(c.CONF_YAML_STATE)})
    if user_input[c.CONF_MODE] != c.MODE_ACTIVE:
        return {c.CONF_MODE: c.MODE_SHADOW, **extra}, {}, {}
    if not user_input.get(CONF_CONFIRM_ACTIVE):
        return {}, {CONF_CONFIRM_ACTIVE: "confirm_active"}, {}
    if yaml_on := yaml_automations_on(hass):
        return {}, {"base": "yaml_still_active"}, {"count": str(len(yaml_on))}
    return {c.CONF_MODE: c.MODE_ACTIVE, **extra}, {}, {}


# ---- flows ---------------------------------------------------------------------------

class LubaConfigFlow(config_entries.ConfigFlow, domain=c.DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors, placeholders = {}, {"missing": ""}
        if user_input is not None:
            update, errors, found = _validate_mower(self.hass, user_input[c.CONF_DEVICE])
            placeholders.update(found)
            if not errors:
                self._opts.update(update)
                return await self.async_step_zones()
        return self.async_show_form(step_id="user", data_schema=_mower_schema(self._opts),
                                    errors=errors, description_placeholders=placeholders)

    async def async_step_zones(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input is not None:
            update, errors = _validate_zones(self.hass, user_input)
            if not errors:
                self._opts.update(update)
                return await self.async_step_inputs()
        return self.async_show_form(
            step_id="zones", data_schema=_zones_schema(self.hass, self._opts[c.CONF_DEVICE], self._opts),
            errors=errors)

    async def async_step_inputs(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._opts.update(_clean(user_input))
            return await self.async_step_gate()
        return self.async_show_form(step_id="inputs", data_schema=_inputs_schema(self.hass, self._opts))

    async def async_step_gate(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._opts.update(user_input)
            return self.async_create_entry(title=c.TITLE, data={},
                                           options={**c.DEFAULTS, **self._opts})
        return self.async_show_form(step_id="gate", data_schema=_gate_schema(self._opts))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LubaOptionsFlow()


class LubaOptionsFlow(config_entries.OptionsFlowWithReload):
    @property
    def _values(self) -> dict[str, Any]:
        return {**c.DEFAULTS, **self.config_entry.options}

    def _save(self, update: dict[str, Any], drop: tuple[str, ...] = ()):
        options = {k: v for k, v in self._values.items() if k not in drop}
        return self.async_create_entry(data={**options, **update})

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(step_id="init",
                                    menu_options=["mower", "zones", "inputs", "gate", "tuning",
                                                  "timing", "mode"])

    async def async_step_mower(self, user_input: dict[str, Any] | None = None):
        errors, placeholders = {}, {"missing": ""}
        if user_input is not None:
            update, errors, found = _validate_mower(self.hass, user_input[c.CONF_DEVICE])
            placeholders.update(found)
            if not errors:
                # A different mower invalidates the zone bindings: re-pick them.
                if update[c.CONF_DEVICE] != self._values.get(c.CONF_DEVICE):
                    update[c.CONF_ZONES] = {}
                return self._save(update)
        return self.async_show_form(step_id="mower", data_schema=_mower_schema(self._values),
                                    errors=errors, description_placeholders=placeholders)

    async def async_step_zones(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input is not None:
            update, errors = _validate_zones(self.hass, user_input)
            if not errors:
                return self._save(update)
        return self.async_show_form(
            step_id="zones",
            data_schema=_zones_schema(self.hass, self._values[c.CONF_DEVICE], self._values),
            errors=errors)

    async def async_step_inputs(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            optional = (c.CONF_WEATHER, c.CONF_PRECIP_TYPE, c.CONF_LIGHTNING_DISTANCE,
                        c.CONF_LIGHTNING_STRIKE, *c.CONF_MOW_ALLOWED.values(), c.CONF_CALENDAR,
                        c.CONF_NOTIFY)
            return self._save(_clean(user_input), drop=optional)
        return self.async_show_form(step_id="inputs", data_schema=_inputs_schema(self.hass, self._values))

    async def async_step_gate(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self._save(user_input)
        return self.async_show_form(step_id="gate", data_schema=_gate_schema(self._values))

    async def async_step_tuning(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input is not None:
            update, errors = _validate_tuning(user_input)
            if not errors:
                return self._save(update)
        return self.async_show_form(step_id="tuning", data_schema=_tuning_schema(self._values),
                                    errors=errors)

    async def async_step_timing(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input is not None:
            update, errors = _validate_timing(user_input, self._values)
            if not errors:
                return self._save(update)
        return self.async_show_form(step_id="timing", data_schema=_timing_schema(self._values),
                                    errors=errors)

    async def async_step_mode(self, user_input: dict[str, Any] | None = None):
        errors, placeholders = {}, {"count": "0"}
        if user_input is not None:
            update, errors, found = _validate_mode(self.hass, user_input)
            placeholders.update(found)
            if not errors:
                return self._save(update, drop=(c.CONF_YAML_STATE,))
        return self.async_show_form(step_id="mode", data_schema=_mode_schema(self._values),
                                    errors=errors, description_placeholders=placeholders)
