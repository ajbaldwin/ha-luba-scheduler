from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.luba import const as c

from .common import GATE, INPUTS, add_mower, setup_luba


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        c.DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_full_flow_binds_by_registry_id(hass):
    mower = add_mower(hass)
    result = await _start(hass)
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {c.CONF_DEVICE: mower.device_id})
    assert result["step_id"] == "zones"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "group_a": [mower.zones["Front"], mower.zones["Side"]], "group_b": [mower.zones["Back"]]})
    assert result["step_id"] == "inputs"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUTS)
    assert result["step_id"] == "gate"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], GATE)
    assert result["type"] is FlowResultType.CREATE_ENTRY

    opts = result["result"].options
    reg = er.async_get(hass)
    assert [b[c.BIND_ID] for b in opts[c.CONF_ZONES]["B"]] == [reg.async_get(mower.zones["Back"]).id]
    assert opts[c.CONF_ZONES]["A"][0][c.BIND_HASH] == "1001"
    assert set(opts[c.CONF_ROLES]) == set(c.MOWER_ROLES)
    assert all(not v.startswith(("sensor.", "switch.")) for v in opts[c.CONF_ROLES].values())
    assert opts[c.CONF_START_FLOOR] == 95                      # defaults filled in
    assert opts[c.CONF_GATE_POLARITY] == c.GATE_ON_CLOSED


async def test_missing_roles_are_named(hass):
    mower = add_mower(hass, skip_roles=(c.ROLE_RTK_FIX,))
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {c.CONF_DEVICE: mower.device_id})
    assert result["errors"] == {"base": "missing_roles"}
    assert result["description_placeholders"]["missing"] == c.ROLE_RTK_FIX


async def test_no_zones(hass):
    mower = add_mower(hass, zones={})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {c.CONF_DEVICE: mower.device_id})
    assert result["errors"] == {"base": "no_zones"}


async def test_zone_groups_must_be_disjoint(hass):
    mower = add_mower(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {c.CONF_DEVICE: mower.device_id})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "group_a": [mower.zones["Front"]], "group_b": [mower.zones["Front"]]})
    assert result["errors"] == {"base": "overlapping_groups"}


async def test_options_tuning_validates_and_types(hass):
    mower = add_mower(hass)
    entry = await setup_luba(hass, mower)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "tuning"})
    good = {c.CONF_CUTOFF_MIN: 45.0, c.CONF_CANOPY_MIN: 50.0, c.CONF_CANOPY_MAX: 92.0,
            c.CONF_PRECIP_MAX: 51.0, c.CONF_LIGHTNING_RADIUS: 5.0, c.CONF_LIGHTNING_RECENCY: 5.0,
            c.CONF_START_FLOOR: 95.0, c.CONF_OPTIMAL_DELAY: 5.0,
            c.CONF_ANGLES: "12, 48", c.CONF_SPACINGS: "28;31"}
    bad = {**good, c.CONF_CANOPY_MAX: 40.0, c.CONF_ANGLES: "12, 200", c.CONF_SPACINGS: "x"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {c.CONF_CANOPY_MAX: "canopy_range", c.CONF_ANGLES: "bad_list",
                                c.CONF_SPACINGS: "bad_list"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], good)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[c.CONF_CUTOFF_MIN] == 45 and isinstance(entry.options[c.CONF_CUTOFF_MIN], int)
    assert entry.options[c.CONF_ANGLES] == [12, 48]
    assert entry.options[c.CONF_SPACINGS] == [28, 31]
    assert entry.options[c.CONF_ZONES]                          # other options kept


async def test_options_clearing_an_optional_input_removes_it(hass):
    mower = add_mower(hass)
    entry = await setup_luba(hass, mower)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "inputs"})
    kept = {k: v for k, v in INPUTS.items() if k != c.CONF_LIGHTNING_DISTANCE}
    result = await hass.config_entries.options.async_configure(result["flow_id"], kept)
    await hass.async_block_till_done()
    assert c.CONF_LIGHTNING_DISTANCE not in entry.options
    assert entry.options[c.CONF_SEASON] == INPUTS[c.CONF_SEASON]


async def _options_step(hass, entry, step):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step})


TIMING = {c.CONF_SCHEDULER_TIME: "09:15:00", c.CONF_ROTATION_TIME: "02:00",
          c.CONF_START_VERIFY: 90.0, c.CONF_START_ATTEMPTS: 2.0, c.CONF_ROUTE_VERIFY: 45.0,
          c.CONF_REPROMPT: 20.0, c.CONF_CANCEL_TIMEOUT: 30.0, c.CONF_RESUME_FLOOR: 25.0,
          c.CONF_OFFLINE_TIMEOUT: 4.0, c.CONF_IDLE_RECONCILE: 3.0}


async def test_options_timing_types_and_normalises(hass):
    mower = add_mower(hass)
    entry = await setup_luba(hass, mower)
    result = await _options_step(hass, entry, "timing")
    assert result["step_id"] == "timing"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**TIMING, c.CONF_RESUME_FLOOR: 99.0})
    assert result["errors"] == {c.CONF_RESUME_FLOOR: "resume_above_start"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], TIMING)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[c.CONF_SCHEDULER_TIME] == "09:15:00"
    assert entry.options[c.CONF_ROTATION_TIME] == "02:00:00"
    assert entry.options[c.CONF_START_ATTEMPTS] == 2
    assert isinstance(entry.options[c.CONF_START_ATTEMPTS], int)
    assert entry.options[c.CONF_ZONES]                          # other options kept


async def test_options_mode_defaults_to_shadow(hass):
    mower = add_mower(hass)
    entry = await setup_luba(hass, mower)
    assert entry.options[c.CONF_MODE] == c.MODE_SHADOW
    result = await _options_step(hass, entry, "mode")
    assert result["step_id"] == "mode"


async def test_options_active_needs_confirmation(hass):
    mower = add_mower(hass)
    entry = await setup_luba(hass, mower)
    result = await _options_step(hass, entry, "mode")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {c.CONF_MODE: c.MODE_ACTIVE, "confirm_active": False})
    assert result["errors"] == {"confirm_active": "confirm_active"}
    assert entry.options[c.CONF_MODE] == c.MODE_SHADOW


async def test_options_active_refused_while_yaml_automation_on(hass):
    mower = add_mower(hass)
    entry = await setup_luba(hass, mower)
    hass.states.async_set("automation.luba_scheduler", "on")
    hass.states.async_set("automation.luba_other", "off")
    result = await _options_step(hass, entry, "mode")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {c.CONF_MODE: c.MODE_ACTIVE, "confirm_active": True})
    assert result["errors"] == {"base": "yaml_still_active"}
    assert result["description_placeholders"]["count"] == "1"
    hass.states.async_set("automation.luba_scheduler", "off")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {c.CONF_MODE: c.MODE_ACTIVE, "confirm_active": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[c.CONF_MODE] == c.MODE_ACTIVE
    assert "confirm_active" not in entry.options
