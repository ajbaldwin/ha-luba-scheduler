from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.luba.const import DOMAIN


async def test_scaffold_flow_aborts(hass):
    """Until P1 lands, adding the integration must never create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_ready"
    assert hass.config_entries.async_entries(DOMAIN) == []
