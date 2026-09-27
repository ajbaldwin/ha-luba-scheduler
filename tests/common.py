"""A fake Mammotion device in the registries, shaped like the live one (spike §1, §3).

Synthetic identifiers only: short hashes and a made-up serial, so the scrub
gate's generic patterns never see a real-looking value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.luba import const as c

UNIQUE = "Luba-TEST0001"
ZONES = {"Front": "1001", "Side": "1002", "Back": "1003", "Slope": "1004"}


@dataclass
class FakeMower:
    device_id: str
    roles: dict[str, str] = field(default_factory=dict)     # role -> entity_id
    zones: dict[str, str] = field(default_factory=dict)     # zone name -> switch entity_id


def add_mower(hass: HomeAssistant, zones: dict[str, str] = ZONES,
              skip_roles: tuple[str, ...] = ()) -> FakeMower:
    mam = MockConfigEntry(domain=c.MAMMOTION, title="Mammotion")
    mam.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mam.entry_id, identifiers={(c.MAMMOTION, UNIQUE)}, name="Test Mower")
    reg = er.async_get(hass)
    mower = FakeMower(device.id)
    for role, (domain, key) in c.MOWER_ROLES.items():
        if role in skip_roles:
            continue
        entry = reg.async_get_or_create(
            domain, c.MAMMOTION, f"{UNIQUE}_{key}", device_id=device.id, config_entry=mam,
            suggested_object_id=f"test_mower_{key}",
            translation_key=None if role in (c.ROLE_MOWER, c.ROLE_CHARGING) else key)
        mower.roles[role] = entry.entity_id
    # Decoys the derivation must not pick: the datalink sensor, and a sensor
    # sharing the area switches' translation_key.
    reg.async_get_or_create("sensor", c.MAMMOTION, f"{UNIQUE}_position_mode", device_id=device.id,
                            config_entry=mam, suggested_object_id="test_mower_rtk_position",
                            translation_key="position_mode")
    reg.async_get_or_create("sensor", c.MAMMOTION, f"{UNIQUE}_area", device_id=device.id,
                            config_entry=mam, suggested_object_id="test_mower_area",
                            translation_key="area")
    for name, zone_hash in zones.items():
        entry = reg.async_get_or_create(
            "switch", c.MAMMOTION, f"{UNIQUE}_{zone_hash}", device_id=device.id, config_entry=mam,
            suggested_object_id=f"test_mower_area_{name.lower()}", translation_key="area",
            original_name=f"Area {name}")
        mower.zones[name] = entry.entity_id
    return mower


INPUTS = {
    c.CONF_SEASON: "input_boolean.season",
    c.CONF_CANOPY: "sensor.canopy",
    c.CONF_PRECIP_CHANCE: "sensor.precip_chance",
    c.CONF_DRY["A"]: "binary_sensor.dry_a",
    c.CONF_DRY["B"]: "binary_sensor.dry_b",
    c.CONF_WEATHER: "weather.home",
    c.CONF_PRECIP_TYPE: "sensor.precip_type",
    c.CONF_LIGHTNING_DISTANCE: "sensor.lightning_distance",
    c.CONF_LIGHTNING_STRIKE: "sensor.lightning_strike",
}
GATE = {c.CONF_GATE: "binary_sensor.gate_closed", c.CONF_GATE_POLARITY: c.GATE_ON_CLOSED}


def set_good_day(hass: HomeAssistant, mower: FakeMower, now: datetime | None = None) -> None:
    """Every input at a value that permits a mow and trips no danger."""
    now = now or dt_util.now()
    states = {
        "input_boolean.season": "on", "sensor.canopy": "70", "sensor.precip_chance": "10",
        "binary_sensor.dry_a": "on", "binary_sensor.dry_b": "on", "weather.home": "sunny",
        "sensor.precip_type": "none", "sensor.lightning_distance": "30",
        "sensor.lightning_strike": (now - timedelta(days=3)).isoformat(),
        "binary_sensor.gate_closed": "on",
        mower.roles[c.ROLE_CAMERA]: "Light", mower.roles[c.ROLE_RTK_FIX]: "Fix",
        mower.roles[c.ROLE_BATTERY]: "100", mower.roles[c.ROLE_ACTIVITY]: "MODE_READY",
    }
    for entity_id, state in states.items():
        hass.states.async_set(entity_id, state)
    hass.states.async_set("sun.sun", "above_horizon", {
        "next_setting": (now + timedelta(hours=5)).isoformat(),
        "next_dusk": (now + timedelta(hours=5, minutes=30)).isoformat(),
    })


def entry_options(hass: HomeAssistant, mower: FakeMower, **overrides) -> dict:
    from custom_components.luba.mammotion import binding_for, derive_roles
    reg = er.async_get(hass)
    roles, missing = derive_roles(hass, mower.device_id)
    assert not missing
    zones = {"A": [binding_for(hass, reg.async_get(mower.zones[z])) for z in ("Front", "Side")],
             "B": [binding_for(hass, reg.async_get(mower.zones["Back"]))]}
    return {**c.DEFAULTS, c.CONF_DEVICE: mower.device_id, c.CONF_ROLES: roles,
            c.CONF_ZONES: zones, **INPUTS, **GATE, **overrides}


async def setup_luba(hass: HomeAssistant, mower: FakeMower, **overrides) -> MockConfigEntry:
    entry = MockConfigEntry(domain=c.DOMAIN, title=c.TITLE, data={},
                            options=entry_options(hass, mower, **overrides))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
