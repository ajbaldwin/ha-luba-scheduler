"""luba.import_yaml_state / luba.export_yaml_state: move state across at cutover and rollback.

``import_yaml_state`` brings the YAML package's state over at cutover (design Q4, P4).
``export_yaml_state`` is the rollback path (design Q10): it returns the same fields,
in the YAML helpers' formats, as service response data; the rollback script writes
them back into its own helpers. It only reads, so it runs in either mode.

The service takes VALUES, not entity ids, so no installation's helper names live
in this code: the cutover script renders them from its own helpers
(``fsm_state: "{{ states('input_select.…') }}"``). Every field is optional and
only the fields given are written, so a re-run is idempotent.

It refuses unless the integration is in shadow mode: importing into a system
that is already commanding the mower would overwrite live decisions. After the
import it runs ``reboot_recover``, which re-arms whatever the imported state
needs (a prompt deadline, a hardware reconcile).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from . import audit
from . import const as c
from .engine.fsm import STATES
from .shadow import EQUIVALENT

SERVICE_IMPORT = "import_yaml_state"
SERVICE_EXPORT = "export_yaml_state"
_BLANK = ("", "unknown", "unavailable", "none", "None")
_EPOCH = "1970-01-01"          # the YAML's "no session" value for session_start


def _text(value: Any) -> str:
    text = str(value).strip()
    return "" if text in _BLANK else text


def _number(kind: type) -> Callable[[Any], Any]:
    def validate(value: Any) -> Any:
        text = _text(value)
        if not text:
            return None                       # unreadable helper: leave the field alone
        try:
            return kind(float(text))
        except ValueError as err:
            raise vol.Invalid(f"not a number: {value!r}") from err
    return validate


def _when(value: Any) -> str:
    """A YAML input_datetime (naive local wall clock) as aware ISO-8601; '' for none."""
    text = _text(value)
    if not text or text.startswith(_EPOCH):
        return ""
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        raise vol.Invalid(f"not a datetime: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed.isoformat()


def _state(blank_ok: bool) -> Callable[[Any], str]:
    def validate(value: Any) -> str:
        text = _text(value)
        if not text and blank_ok:
            return ""
        text = EQUIVALENT.get(text, text)
        if text not in STATES:
            raise vol.Invalid(f"not an FSM state: {value!r}")
        return text
    return validate


def _group(value: Any) -> str:
    text = _text(value)
    if text not in ("", *c.GROUPS):
        raise vol.Invalid(f"not a group: {value!r}")
    return text


# field -> (store section, attribute)
FIELDS: dict[str, tuple[str, str]] = {
    "prior_state": ("fsm", "prior_state"),
    "error_from": ("fsm", "error_from"),
    "session_start": ("session", "start"),
    "session_battery_start": ("session", "battery_start"),
    "session_work_area": ("session", "work_area"),
    "session_recharge_count": ("session", "recharge_count"),
    "session_abort_reason": ("session", "abort_reason"),
    "active_group": ("session", "active_group"),
    "scheduled_group": ("day", "scheduled_group"),
    "evaluated_at": ("day", "evaluated_at"),
    "last_counted_cut": ("counters", "last_counted_cut"),
    "last_logged_cut": ("counters", "last_logged_cut"),
    "angle_1": ("settings", "angle_1"),
    "spacing": ("settings", "spacing"),
    "cutting_height": ("settings", "cutting_height"),
    "cuts_per_group": ("settings", "cuts_per_group"),
    "auto_start": ("settings", "auto_start"),
}

SCHEMA = vol.Schema({
    vol.Optional("fsm_state"): _state(blank_ok=False),
    vol.Optional("prior_state"): _state(blank_ok=True),
    vol.Optional("error_from"): _state(blank_ok=True),
    vol.Optional("session_start"): _when,
    vol.Optional("session_battery_start"): _number(float),
    vol.Optional("session_work_area"): _text,
    vol.Optional("session_recharge_count"): _number(int),
    vol.Optional("session_abort_reason"): _text,
    vol.Optional("active_group"): _group,
    vol.Optional("scheduled_group"): _group,
    vol.Optional("evaluated_at"): _when,
    vol.Optional("cuts_a"): _number(int),
    vol.Optional("cuts_b"): _number(int),
    vol.Optional("last_counted_cut"): _text,
    vol.Optional("last_logged_cut"): _text,
    vol.Optional("angle_1"): _number(int),
    vol.Optional("spacing"): _number(int),
    vol.Optional("cutting_height"): _number(int),
    vol.Optional("cuts_per_group"): vol.All(_number(int), vol.Any(None, vol.In(c.CUTS_PER_GROUP_OPTIONS))),
    vol.Optional("auto_start"): cv.boolean,
})


def _wall(value: str) -> str:
    """An aware ISO timestamp as the YAML's naive local wall clock; the epoch for none."""
    parsed = dt_util.parse_datetime(value) if value else None
    if parsed is None:
        return f"{_EPOCH} 00:00:00"
    return dt_util.as_local(parsed).strftime("%Y-%m-%d %H:%M:%S")


def export_state(co) -> dict[str, Any]:
    """The import's fields, as the YAML holds them. ``import_yaml_state`` reads this back
    unchanged (to the second), so an export → import round trip changes nothing."""
    store = co.store
    data: dict[str, Any] = {"fsm_state": store.fsm.state}
    for key, (section, attr) in FIELDS.items():
        data[key] = getattr(getattr(store, section), attr)
    data.update(
        session_start=_wall(store.session.start),
        evaluated_at=_wall(store.day.evaluated_at),
        session_battery_start=store.session.battery_start or 0,    # the YAML helper's floor
        angle_1=co.angle_1,                       # resolved: an unset one is the first entry
        spacing=co.spacing,
    )
    for group in c.GROUPS:
        data[f"cuts_{group.lower()}"] = store.counters.cuts.get(group, 0)
    return data


@callback
def async_register_services(hass: HomeAssistant, co) -> Callable[[], None]:
    async def _import(call: ServiceCall) -> None:
        if co.opts.get(c.CONF_MODE, c.MODE_SHADOW) != c.MODE_SHADOW:
            raise ServiceValidationError(translation_domain=c.DOMAIN,
                                         translation_key="import_needs_shadow")
        store, data, changed = co.store, dict(call.data), []
        for key, (section, attr) in FIELDS.items():
            if key in data and data[key] is not None:
                target = getattr(store, section)
                if getattr(target, attr) != data[key]:
                    setattr(target, attr, data[key])
                    changed.append(key)
        for group in c.GROUPS:
            value = data.get(f"cuts_{group.lower()}")
            if value is not None and store.counters.cuts.get(group) != value:
                store.counters.cuts[group] = value
                changed.append(f"cuts_{group.lower()}")
        if "fsm_state" in data:
            result = await co.fsm.restore(data["fsm_state"])
            if result.status == "ok":
                changed.append("fsm_state")
        await store.async_save()
        co.recompute()
        audit.log(hass, f"import_yaml_state: {len(changed)} field(s) changed"
                        f"{': ' + ', '.join(changed) if changed else ''}")
        co.dispatcher.dispatch("reboot_recover")

    async def _export(_call: ServiceCall) -> ServiceResponse:
        data = export_state(co)
        audit.log(hass, f"export_yaml_state: read (FSM {data['fsm_state']})")
        return data

    hass.services.async_register(c.DOMAIN, SERVICE_IMPORT, _import, schema=SCHEMA)
    hass.services.async_register(c.DOMAIN, SERVICE_EXPORT, _export,
                                 supports_response=SupportsResponse.ONLY)

    @callback
    def _remove() -> None:
        hass.services.async_remove(c.DOMAIN, SERVICE_IMPORT)
        hass.services.async_remove(c.DOMAIN, SERVICE_EXPORT)
    return _remove
