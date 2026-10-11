from __future__ import annotations

import copy
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.wol_daemon.const import DOMAIN

URL = "http://wol.local:9090"
API_KEY = "secret-key"
INSTANCE_ID = "3f1c0d9a6b6e4c4f9a1e2b7d5c8a9f01"

INFO = {"instance_id": INSTANCE_ID, "status_timeout_seconds": 5, "access": "control", "key_name": "Home Assistant"}

MACHINES = [
    {
        "key": "nas",
        "name": "NAS",
        "online": True,
        "ip_address": "10.0.0.1",
        "mac_address": "AA:BB:CC:DD:EE:01",
        "shutdown_method": "ssh",
        "clusters": ["homelab"],
        "last_action": {
            "time": "2026-10-11T07:00:02+02:00",
            "action": "on",
            "source": "schedule",
            "result": "ok",
            "detail": "",
        },
        "next_action": {
            "rule": "Night",
            "action": "off",
            "time": "2026-10-11T23:00:00+02:00",
            "will_be_skipped": False,
        },
    },
    {
        "key": "tv",
        "name": "TV",
        "online": False,
        "ip_address": "10.0.0.2",
        "mac_address": "AA:BB:CC:DD:EE:02",
        "shutdown_method": "none",
        "clusters": ["homelab"],
        "last_action": None,
        "next_action": None,
    },
]

CLUSTERS = [
    {
        "key": "homelab",
        "name": "Homelab",
        "state": "partial",
        "online": 1,
        "total": 2,
        "delay_seconds": 60,
        "max_wait_seconds": 300,
        "members": [{"key": "nas", "name": "NAS", "online": True}, {"key": "tv", "name": "TV", "online": False}],
        "last_action": None,
        "next_action": None,
    }
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def daemon(aioclient_mock: AiohttpClientMocker):
    """A fake daemon; change its state, then call mock() to (re)register the responses."""

    class FakeDaemon:
        def __init__(self) -> None:
            self.info: dict[str, Any] = copy.deepcopy(INFO)
            self.machines: list[dict[str, Any]] = copy.deepcopy(MACHINES)
            self.clusters: list[dict[str, Any]] = copy.deepcopy(CLUSTERS)
            self.status = 200

        def mock(self) -> None:
            aioclient_mock.clear_requests()
            body = {"error": "API key required"} if self.status == 401 else None
            aioclient_mock.get(f"{URL}/api/info", status=self.status, json=body or self.info)
            aioclient_mock.get(f"{URL}/api/machines", status=self.status, json=body or {"machines": self.machines})
            aioclient_mock.get(f"{URL}/api/clusters", status=self.status, json=body or {"clusters": self.clusters})

    fake = FakeDaemon()
    fake.mock()
    return fake


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WOL Daemon (wol.local)",
        unique_id=INSTANCE_ID,
        data={"url": URL, "api_key": API_KEY},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(hass, daemon, config_entry):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
