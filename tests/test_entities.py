from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.wol_daemon.const import DOMAIN

from .conftest import INSTANCE_ID, URL


def _posts(aioclient_mock) -> list[str]:
    return [str(url) for method, url, *_ in aioclient_mock.mock_calls if method == "POST"]


async def _poll(hass) -> None:
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_entities(hass, setup_integration):
    assert setup_integration.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.nas_online").state == STATE_ON
    assert hass.states.get("binary_sensor.tv_online").state == STATE_OFF
    assert hass.states.get("switch.nas_power").state == STATE_ON

    last = hass.states.get("sensor.nas_last_action")
    assert last.state == "2026-10-11T05:00:02+00:00"
    assert last.attributes["source"] == "schedule"
    nxt = hass.states.get("sensor.nas_next_scheduled_action")
    assert nxt.attributes["rule"] == "Night"
    assert hass.states.get("sensor.tv_last_action").state == "unknown"

    assert hass.states.get("sensor.homelab_state").state == "partial"
    members = hass.states.get("sensor.homelab_machines_online")
    assert members.state == "1"
    assert members.attributes["total"] == 2
    assert members.attributes["members"] == {"NAS": True, "TV": False}

    for entity_id in (
        "button.nas_wake",
        "button.nas_shut_down",
        "button.nas_reboot",
        "button.tv_wake",
        "button.homelab_wake_all",
        "button.homelab_shut_down_all",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    # Wake-only machine: no switch, no shutdown or reboot.
    assert hass.states.get("switch.tv_power") is None
    assert hass.states.get("button.tv_shut_down") is None
    assert hass.states.get("button.tv_reboot") is None


async def test_devices(hass, setup_integration):
    registry = dr.async_get(hass)
    hub = registry.async_get_device(identifiers={(DOMAIN, INSTANCE_ID)})
    nas = registry.async_get_device(identifiers={(DOMAIN, f"{INSTANCE_ID}-machine-nas")})
    cluster = registry.async_get_device(identifiers={(DOMAIN, f"{INSTANCE_ID}-cluster-homelab")})
    assert nas.name == "NAS"
    assert nas.via_device_id == hub.id
    assert (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:01") in nas.connections
    assert nas.configuration_url == f"{URL}/machines/nas"
    assert cluster.via_device_id == hub.id


async def test_read_only_key_has_no_controls(hass, daemon, config_entry):
    daemon.info["access"] = "read"
    daemon.mock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.nas_online") is not None
    assert hass.states.async_entity_ids("button") == []
    assert hass.states.async_entity_ids("switch") == []


@pytest.mark.parametrize(
    ("entity_id", "path"),
    [
        ("button.nas_wake", "/api/machines/nas/action/on"),
        ("button.nas_shut_down", "/api/machines/nas/action/off"),
        ("button.nas_reboot", "/api/machines/nas/action/reboot"),
        ("button.homelab_wake_all", "/api/clusters/homelab/action/on"),
        ("button.homelab_shut_down_all", "/api/clusters/homelab/action/off"),
    ],
)
async def test_buttons(hass, setup_integration, aioclient_mock, entity_id, path):
    aioclient_mock.post(f"{URL}{path}", json={"result": "ok"})
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    assert _posts(aioclient_mock) == [f"{URL}{path}"]
    # The request carries the key.
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer secret-key"


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (502, {"result": "error", "detail": "ssh: connection refused"}, "ssh: connection refused"),
        (403, {"error": "API key 'Home Assistant' is read-only"}, "read-only"),
        (409, {"error": "'NAS' has no shutdown method configured"}, "no shutdown method"),
    ],
)
async def test_action_errors_are_shown(hass, setup_integration, aioclient_mock, status, body, message):
    aioclient_mock.post(f"{URL}/api/machines/nas/action/off", status=status, json=body)
    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call("button", "press", {"entity_id": "button.nas_shut_down"}, blocking=True)


async def test_rejected_key_on_action_starts_reauth(hass, setup_integration, aioclient_mock):
    aioclient_mock.post(f"{URL}/api/machines/nas/action/on", status=401, json={"error": "API key required"})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("button", "press", {"entity_id": "button.nas_wake"}, blocking=True)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_switch_shows_requested_state_while_switching(hass, setup_integration, daemon, aioclient_mock):
    aioclient_mock.post(f"{URL}/api/machines/nas/action/off", json={"result": "ok"})
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.nas_power"}, blocking=True)
    await hass.async_block_till_done()

    # Still pinging while it shuts down: the switch stays off instead of jumping back.
    state = hass.states.get("switch.nas_power")
    assert state.state == STATE_OFF
    assert state.attributes["switching"] is True

    # Once it's down, it simply follows the machine again.
    daemon.machines[0]["online"] = False
    daemon.mock()
    await _poll(hass)
    state = hass.states.get("switch.nas_power")
    assert state.state == STATE_OFF
    assert state.attributes["switching"] is False

    daemon.machines[0]["online"] = True  # switched on by hand
    daemon.mock()
    await _poll(hass)
    assert hass.states.get("switch.nas_power").state == STATE_ON


async def test_switch_gives_up_waiting(hass, setup_integration, aioclient_mock, freezer):
    aioclient_mock.post(f"{URL}/api/machines/nas/action/off", json={"result": "ok"})
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.nas_power"}, blocking=True)
    assert hass.states.get("switch.nas_power").state == STATE_OFF

    freezer.tick(timedelta(minutes=6))
    await _poll(hass)
    assert hass.states.get("switch.nas_power").state == STATE_ON


async def test_new_machine_gets_entities(hass, setup_integration, daemon):
    daemon.machines.append({**daemon.machines[1], "key": "pc", "name": "PC", "mac_address": "AA:BB:CC:DD:EE:03"})
    daemon.mock()
    await _poll(hass)
    assert hass.states.get("binary_sensor.pc_online") is not None
    assert hass.states.get("button.pc_wake") is not None


async def test_deleted_machine_loses_its_device(hass, setup_integration, daemon):
    registry = dr.async_get(hass)
    identifier = (DOMAIN, f"{INSTANCE_ID}-machine-tv")
    assert registry.async_get_device(identifiers={identifier}) is not None

    daemon.machines.pop(1)
    daemon.clusters[0]["members"].pop(1)
    daemon.mock()
    await _poll(hass)
    assert registry.async_get_device(identifiers={identifier}) is None
    assert er.async_get(hass).async_get("binary_sensor.tv_online") is None

    # And it comes back if it's added again.
    daemon.machines.append({**daemon.machines[0], "key": "tv", "name": "TV", "mac_address": "AA:BB:CC:DD:EE:02"})
    daemon.mock()
    await _poll(hass)
    assert hass.states.get("binary_sensor.tv_online") is not None


async def test_unreachable_daemon_makes_entities_unavailable(hass, setup_integration, daemon, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/machines", exc=TimeoutError())
    aioclient_mock.get(f"{URL}/api/clusters", exc=TimeoutError())
    await _poll(hass)
    assert hass.states.get("binary_sensor.nas_online").state == STATE_UNAVAILABLE
    # Devices stay: an outage is not a deletion.
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{INSTANCE_ID}-machine-nas")}) is not None


async def test_rejected_key_while_polling_starts_reauth(hass, setup_integration, daemon):
    daemon.status = 401
    daemon.mock()
    await _poll(hass)
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_setup_retries_while_daemon_is_down(hass, aioclient_mock, config_entry):
    aioclient_mock.get(f"{URL}/api/info", exc=TimeoutError())
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
