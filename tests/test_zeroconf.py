from __future__ import annotations

from ipaddress import ip_address

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wol_daemon.const import DOMAIN

from .conftest import API_KEY, INFO, INSTANCE_ID

DISCOVERED_URL = "http://192.168.1.5:9090"


def _discovery(instance_id: str | None = INSTANCE_ID, host: str = "192.168.1.5") -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=9090,
        hostname="pi.local.",
        type="_wol-daemon._tcp.local.",
        name="WOL Daemon (pi)._wol-daemon._tcp.local.",
        properties={"id": instance_id} if instance_id else {},
    )


async def _discover(hass, info: ZeroconfServiceInfo):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )


async def test_discovered_daemon_asks_only_for_key(hass, aioclient_mock):
    aioclient_mock.get(f"{DISCOVERED_URL}/api/info", json=INFO)
    result = await _discover(hass, _discovery())
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {"url": DISCOVERED_URL}
    flow = hass.config_entries.flow.async_get(result["flow_id"])
    assert flow["context"]["title_placeholders"] == {"name": "WOL Daemon (pi)"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": API_KEY})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"url": DISCOVERED_URL, "api_key": API_KEY}
    assert result["result"].unique_id == INSTANCE_ID


async def test_wrong_key_on_discovered_daemon(hass, aioclient_mock):
    aioclient_mock.get(f"{DISCOVERED_URL}/api/info", status=401, json={"error": "API key required"})
    result = await _discover(hass, _discovery())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}


async def test_discovery_without_id_is_ignored(hass):
    result = await _discover(hass, _discovery(instance_id=None))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_wol_daemon"


async def test_known_daemon_with_ip_url_follows_new_address(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=INSTANCE_ID, data={"url": "http://192.168.1.4:9090", "api_key": API_KEY}
    )
    entry.add_to_hass(hass)
    result = await _discover(hass, _discovery())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["url"] == DISCOVERED_URL


async def test_known_daemon_with_hostname_keeps_its_url(hass, config_entry):
    url = config_entry.data["url"]  # http://wol.local:9090
    result = await _discover(hass, _discovery())
    assert result["reason"] == "already_configured"
    assert config_entry.data["url"] == url


async def test_key_from_other_daemon_than_discovered(hass, aioclient_mock):
    aioclient_mock.get(f"{DISCOVERED_URL}/api/info", json={**INFO, "instance_id": "someone-else"})
    result = await _discover(hass, _discovery())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": API_KEY})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_daemon"
