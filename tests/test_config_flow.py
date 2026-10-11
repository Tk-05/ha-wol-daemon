from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.wol_daemon.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import API_KEY, INSTANCE_ID, URL


async def test_user_flow(hass, daemon):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    # Without scheme and with a trailing slash, as people type it.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "wol.local:9090/", "api_key": API_KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WOL Daemon (wol.local)"
    assert result["data"] == {"url": URL, "api_key": API_KEY}
    assert result["result"].unique_id == INSTANCE_ID


@pytest.mark.parametrize(("status", "error"), [(401, "invalid_auth"), (500, "cannot_connect")])
async def test_user_flow_errors(hass, daemon, aioclient_mock, status, error):
    daemon.status = status
    daemon.mock()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": URL, "api_key": "wrong"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    # Fixing it continues the same form.
    daemon.status = 200
    daemon.mock()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": URL, "api_key": API_KEY})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_old_daemon_without_info(hass, aioclient_mock):
    aioclient_mock.get(f"{URL}/api/info", status=404, json={"error": "not found"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": URL, "api_key": API_KEY})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_daemon_new_address_updates_entry(hass, daemon, config_entry, aioclient_mock):
    aioclient_mock.get("http://10.0.0.9:9090/api/info", json=daemon.info)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://10.0.0.9:9090", "api_key": API_KEY}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data["url"] == "http://10.0.0.9:9090"


async def test_reauth(hass, setup_integration, daemon):
    entry = setup_integration
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "new-key"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "new-key"


async def test_reauth_with_other_daemon_is_refused(hass, setup_integration, daemon):
    entry = setup_integration
    result = await entry.start_reauth_flow(hass)
    daemon.info["instance_id"] = "someone-else"
    daemon.mock()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "new-key"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_daemon"
    assert entry.data["api_key"] == API_KEY


async def test_reconfigure(hass, setup_integration, daemon, aioclient_mock):
    entry = setup_integration
    aioclient_mock.get("http://10.0.0.9:9090/api/info", json=daemon.info)
    aioclient_mock.get("http://10.0.0.9:9090/api/machines", json={"machines": daemon.machines})
    aioclient_mock.get("http://10.0.0.9:9090/api/clusters", json={"clusters": daemon.clusters})
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://10.0.0.9:9090", "api_key": API_KEY}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["url"] == "http://10.0.0.9:9090"


async def test_options(hass, setup_integration):
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 60})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert entry.runtime_data.update_interval.total_seconds() == 60
