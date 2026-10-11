from __future__ import annotations

from custom_components.wol_daemon.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_hide_secrets(hass, setup_integration):
    result = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert result["entry"]["data"]["api_key"] == "**REDACTED**"
    nas = result["data"]["machines"]["nas"]
    assert nas["ip_address"] == "**REDACTED**"
    assert nas["mac_address"] == "**REDACTED**"
    assert nas["online"] is True
    assert result["info"]["instance_id"]
