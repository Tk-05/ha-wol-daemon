from __future__ import annotations

import asyncio

import pytest

from custom_components.wol_daemon import events as events_module

from .conftest import INSTANCE_ID

HELLO = {"type": "hello", "instance_id": INSTANCE_ID}


async def _settle(hass, seconds: float = 0.05) -> None:
    """Lets the background listener run (it isn't waited for by async_block_till_done)."""
    await asyncio.sleep(seconds)
    await hass.async_block_till_done()


@pytest.fixture
def fast_retry(monkeypatch):
    monkeypatch.setattr(events_module, "EVENTS_RETRY_MIN", 0.01)
    monkeypatch.setattr(events_module, "EVENTS_RETRY_MAX", 0.01)


async def test_change_event_refreshes(hass, daemon, config_entry):
    daemon.events = [HELLO, {"type": "action", "kind": "machine", "key": "nas", "action": "on", "result": "ok"}]
    daemon.mock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await _settle(hass)
    # Setup, then once for the event; the hello of the first connection doesn't count.
    assert daemon.calls("/api/machines") == 2
    assert daemon.calls("/api/events") == 1


async def test_hello_alone_doesnt_refresh(hass, daemon, config_entry):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await _settle(hass)
    assert daemon.calls("/api/machines") == 1


async def test_reconnects_and_refreshes_after_reconnect(hass, daemon, config_entry, fast_retry):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await _settle(hass, 0.2)
    # The stream keeps ending; every reconnect may have missed events, so it refreshes
    # (debounced, so not once per reconnect).
    assert daemon.calls("/api/events") >= 3
    assert daemon.calls("/api/machines") >= 2


async def test_old_daemon_without_event_stream(hass, daemon, config_entry, fast_retry):
    daemon.events_status = 404
    daemon.mock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await _settle(hass, 0.1)
    assert daemon.calls("/api/events") == 1
    assert hass.states.get("binary_sensor.nas_online").state == "on"


async def test_stream_errors_are_retried(hass, daemon, config_entry, aioclient_mock, fast_retry):
    daemon.events_status = 500
    daemon.mock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await _settle(hass, 0.1)
    assert daemon.calls("/api/events") >= 2


async def test_listener_stops_with_the_entry(hass, daemon, config_entry, fast_retry):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await _settle(hass)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    before = daemon.calls("/api/events")
    await _settle(hass, 0.1)
    assert daemon.calls("/api/events") == before
