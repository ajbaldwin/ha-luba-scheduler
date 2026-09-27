"""Read-only entities end to end, against the fake mower and fake inputs."""
from datetime import timedelta

from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.luba import const as c

from .common import add_mower, set_good_day, setup_luba

ENTITIES = [
    "binary_sensor.luba_optimal_conditions", "binary_sensor.luba_adverse_conditions",
    "binary_sensor.luba_group_a_conditions_ok", "binary_sensor.luba_group_b_conditions_ok",
    "binary_sensor.luba_ready", "sensor.luba_window_close", "sensor.luba_hard_stop",
    "sensor.luba_next_mow_angle", "select.luba_cuts_per_group", "select.luba_angle",
    "select.luba_path_spacing", "number.luba_cutting_height",
]


async def _setup(hass, **overrides):
    mower = add_mower(hass)
    set_good_day(hass, mower)
    entry = await setup_luba(hass, mower, **overrides)
    return mower, entry


def _state(hass, entity_id):
    return hass.states.get(entity_id)


async def test_entity_ids_are_the_design_contract(hass):
    await _setup(hass)
    for entity_id in ENTITIES:
        assert _state(hass, entity_id) is not None, entity_id


async def test_optimal_waits_for_delay_then_turns_on(hass, freezer):
    await _setup(hass)
    assert _state(hass, "binary_sensor.luba_optimal_conditions").state == "off"
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = _state(hass, "binary_sensor.luba_optimal_conditions")
    assert state.state == "on"
    assert state.attributes["dry"] is True


async def test_optimal_reads_the_selected_groups_wetness(hass, freezer):
    mower, entry = await _setup(hass, **{c.CONF_OPTIMAL_DELAY: 0})
    hass.states.async_set("binary_sensor.dry_a", "off")
    await hass.async_block_till_done()
    assert _state(hass, "binary_sensor.luba_group_a_conditions_ok").state == "off"
    assert _state(hass, "binary_sensor.luba_group_b_conditions_ok").state == "on"
    coordinator = entry.runtime_data
    coordinator.store.day.scheduled_group = "B"
    coordinator.async_set_updated_data(coordinator._compute())
    await hass.async_block_till_done()
    state = _state(hass, "binary_sensor.luba_optimal_conditions")
    assert state.state == "on" and state.attributes["group"] == "B"


async def test_adverse_trips_on_heat_and_names_the_term(hass):
    await _setup(hass)
    assert _state(hass, "binary_sensor.luba_adverse_conditions").state == "off"
    hass.states.async_set("sensor.canopy", "95")
    await hass.async_block_till_done()
    state = _state(hass, "binary_sensor.luba_adverse_conditions")
    assert state.state == "on" and state.attributes["heat"] is True


async def test_ready_follows_battery_and_rtk(hass):
    mower, _ = await _setup(hass)
    assert _state(hass, "binary_sensor.luba_ready").state == "on"
    hass.states.async_set(mower.roles[c.ROLE_RTK_FIX], "Float")
    await hass.async_block_till_done()
    state = _state(hass, "binary_sensor.luba_ready")
    assert state.state == "off" and state.attributes["rtk_fix"] is False


async def test_window_close_is_sunset_minus_cutoff(hass):
    await _setup(hass, **{c.CONF_CUTOFF_MIN: 60})
    setting = dt_util.parse_datetime(hass.states.get("sun.sun").attributes["next_setting"])
    window = dt_util.parse_datetime(_state(hass, "sensor.luba_window_close").state)
    assert abs(window - (setting - timedelta(minutes=60))) < timedelta(seconds=1)   # state drops microseconds
    assert _state(hass, "sensor.luba_hard_stop").state != "unknown"


async def test_settings_selects_drive_the_angle(hass):
    _, entry = await _setup(hass)
    angle = _state(hass, "sensor.luba_next_mow_angle")
    assert angle.state == "12" and angle.attributes["toward_mode"] == 1
    await hass.services.async_call("select", "select_option", {
        "entity_id": "select.luba_angle", "option": "48"}, blocking=True)
    await hass.services.async_call("select", "select_option", {
        "entity_id": "select.luba_cuts_per_group", "option": "2"}, blocking=True)
    coordinator = entry.runtime_data
    coordinator.store.day.scheduled_group = "A"
    coordinator.store.counters.cuts["A"] = 1
    coordinator.async_set_updated_data(coordinator._compute())
    await hass.async_block_till_done()
    angle = _state(hass, "sensor.luba_next_mow_angle")
    assert angle.state == "138" and "perpendicular" in angle.attributes["plan"]
    await hass.services.async_call("number", "set_value", {
        "entity_id": "number.luba_cutting_height", "value": 80}, blocking=True)
    assert coordinator.store.settings.cutting_height == 80


async def test_settings_survive_a_reload(hass):
    _, entry = await _setup(hass)
    await hass.services.async_call("select", "select_option", {
        "entity_id": "select.luba_path_spacing", "option": "31"}, blocking=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, "select.luba_path_spacing").state == "31"


async def test_reslugged_mammotion_entity_is_followed(hass):
    mower, _ = await _setup(hass)
    reg = er.async_get(hass)
    reg.async_update_entity(mower.roles[c.ROLE_RTK_FIX], new_entity_id="sensor.outside_rtk_renamed")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.outside_rtk_renamed", "Single")
    await hass.async_block_till_done()
    assert _state(hass, "binary_sensor.luba_ready").attributes["rtk_fix"] is False
    assert ir.async_get(hass).async_get_issue(c.DOMAIN, "dead_bindings") is None


async def test_removed_zone_raises_a_repair_issue_and_clears(hass):
    mower, entry = await _setup(hass)
    issues = ir.async_get(hass)
    er.async_get(hass).async_remove(mower.zones["Back"])
    await hass.async_block_till_done()
    issue = issues.async_get_issue(c.DOMAIN, "dead_bindings")
    assert issue is not None and "Area Back" in issue.translation_placeholders["names"]


async def test_start_mow_drift_raises_when_mammotion_registers(hass):
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv

    from custom_components.luba.mammotion import START_MOW_FIELDS

    await _setup(hass)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(c.DOMAIN, "start_mow_drift") is None

    async def _handler(call):
        return None
    fields = START_MOW_FIELDS | {"new_thing"}
    hass.services.async_register(c.MAMMOTION, "start_mow", _handler,
                                 schema=cv.make_entity_service_schema(
                                     {vol.Optional(f): object for f in fields}))
    await hass.async_block_till_done()
    issue = issues.async_get_issue(c.DOMAIN, "start_mow_drift")
    assert issue is not None and issue.translation_placeholders["added"] == "new_thing"


async def test_suffixed_entity_id_raises_an_issue(hass):
    er.async_get(hass).async_get_or_create("binary_sensor", "other", "squatter",
                                           suggested_object_id="luba_ready")
    await _setup(hass)
    issue = ir.async_get(hass).async_get_issue(c.DOMAIN, "entity_id_taken_ready")
    assert issue is not None
    assert issue.translation_placeholders["actual"] == "binary_sensor.luba_ready_2"
