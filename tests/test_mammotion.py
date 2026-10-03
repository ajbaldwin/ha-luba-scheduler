"""Binding, derivation and drift against a fake Mammotion device (spike §1–§3)."""
import voluptuous as vol
from homeassistant.helpers import config_validation as cv, entity_registry as er

from custom_components.luba import const as c
from custom_components.luba.mammotion import (
    START_MOW_FIELDS, area_switches, binding_for, dead_bindings, derive_roles, resolve,
    start_mow_drift, task_area_sensor)

from .common import UNIQUE, add_mower


async def test_derive_roles_matches_unique_ids_not_decoys(hass):
    mower = add_mower(hass)
    roles, missing = derive_roles(hass, mower.device_id)
    assert missing == []
    reg = er.async_get(hass)
    assert {r: reg.async_get(i).entity_id for r, i in roles.items()} == mower.roles
    # the fix-quality sensor, never the datalink decoy
    assert reg.async_get(roles[c.ROLE_RTK_FIX]).unique_id == f"{UNIQUE}_positioning_mode"


async def test_derive_roles_reports_missing(hass):
    mower = add_mower(hass, skip_roles=(c.ROLE_RTK_FIX, c.ROLE_CHARGING))
    _, missing = derive_roles(hass, mower.device_id)
    assert set(missing) == {c.ROLE_RTK_FIX, c.ROLE_CHARGING}


async def test_area_switches_excludes_area_sensor(hass):
    mower = add_mower(hass)
    assert {e.entity_id for e in area_switches(hass, mower.device_id)} == set(mower.zones.values())


async def test_binding_survives_reslug_and_same_name_rehash(hass):
    mower = add_mower(hass)
    reg = er.async_get(hass)
    binding = binding_for(hass, reg.async_get(mower.zones["Back"]))
    assert binding[c.BIND_HASH] == "1003" and binding[c.BIND_NAME] == "Area Back"

    # entity_id re-slug (the outside_ prefix, a user rename)
    reg.async_update_entity(mower.zones["Back"], new_entity_id="switch.outside_test_mower_area_back")
    assert resolve(hass, binding[c.BIND_ID]) == "switch.outside_test_mower_area_back"
    # Mammotion's in-place re-key on a same-name re-hash
    reg.async_update_entity("switch.outside_test_mower_area_back", new_unique_id=f"{UNIQUE}_2003")
    assert resolve(hass, binding[c.BIND_ID]) == "switch.outside_test_mower_area_back"
    assert dead_bindings(hass, [binding[c.BIND_ID]]) == []


async def test_rebuilt_zone_is_a_dead_binding(hass):
    mower = add_mower(hass)
    reg = er.async_get(hass)
    binding = binding_for(hass, reg.async_get(mower.zones["Back"]))
    reg.async_remove(mower.zones["Back"])       # the 08-16 shape: new hash AND new name
    assert dead_bindings(hass, [binding[c.BIND_ID]]) == [binding[c.BIND_ID]]


async def test_task_area_sensor_is_derived_from_the_switch(hass):
    mower = add_mower(hass)
    reg = er.async_get(hass)
    switch_id = reg.async_get(mower.zones["Side"]).id
    assert task_area_sensor(hass, switch_id) is None            # no job, no sensor
    sensor = reg.async_get_or_create("sensor", c.MAMMOTION, f"{UNIQUE}_1002_task_area",
                                     suggested_object_id="whatever_the_slug_is")
    assert task_area_sensor(hass, switch_id) == sensor.entity_id


def _register_start_mow(hass, fields):
    async def _handler(call):
        return None
    schema = cv.make_entity_service_schema({vol.Optional(f): object for f in fields})
    hass.services.async_register(c.MAMMOTION, "start_mow", _handler, schema=schema)


async def test_drift_absent_ok_added_removed(hass):
    assert start_mow_drift(hass)[0] == "absent"
    _register_start_mow(hass, START_MOW_FIELDS)
    assert start_mow_drift(hass) == ("ok", set(), set())
    hass.services.async_remove(c.MAMMOTION, "start_mow")
    _register_start_mow(hass, (START_MOW_FIELDS - {"is_dump"}) | {"new_thing"})
    assert start_mow_drift(hass) == ("drift", {"new_thing"}, {"is_dump"})


async def test_drift_ignores_retired_rain_tactics(hass):
    """Mammotion 0.6.14 accepts rain_tactics again (ignored); 0.6.11-0.6.13 don't."""
    _register_start_mow(hass, START_MOW_FIELDS | {"rain_tactics"})
    assert start_mow_drift(hass) == ("ok", set(), set())


async def test_commander_never_sends_a_retired_field():
    """Sending one raises Mammotion's own "retired option" repair."""
    from custom_components.luba.commander import FIXED_JOB
    from custom_components.luba.mammotion import RETIRED_START_MOW_FIELDS
    assert not RETIRED_START_MOW_FIELDS & set(FIXED_JOB)


async def test_drift_reads_the_ha_2026_9_wrapping(hass):
    """HA 2026.9 wraps the entity-service vol.All in an outer vol.Schema (live 2026.9.4)."""
    async def _handler(call):
        return None
    inner = cv.make_entity_service_schema({vol.Optional(f): object for f in START_MOW_FIELDS})
    hass.services.async_register(c.MAMMOTION, "start_mow", _handler, schema=vol.Schema(inner))
    assert start_mow_drift(hass) == ("ok", set(), set())


async def test_drift_unreadable(hass):
    async def _handler(call):
        return None
    hass.services.async_register(c.MAMMOTION, "start_mow", _handler, schema=lambda v: v)
    assert start_mow_drift(hass)[0] == "unreadable"
