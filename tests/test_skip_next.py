from __future__ import annotations

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError

from .conftest import URL

NEXT = {"rule": "Night", "action": "off", "time": "2026-10-11T23:00:00+02:00", "will_be_skipped": False}


def _requests(aioclient_mock, method: str) -> list[str]:
    return [str(url) for m, url, *_ in aioclient_mock.mock_calls if m == method]


async def test_switches_follow_next_action(hass, setup_integration):
    nas = hass.states.get("switch.nas_skip_next_scheduled_action")
    assert nas.state == STATE_OFF
    assert nas.attributes["rule"] == "Night"
    assert nas.attributes["time"] == "2026-10-11T23:00:00+02:00"
    # No schedule: nothing to skip.
    assert hass.states.get("switch.tv_skip_next_scheduled_action").state == STATE_UNAVAILABLE
    assert hass.states.get("switch.homelab_skip_next_scheduled_action").state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("entity_id", "path"),
    [
        ("switch.nas_skip_next_scheduled_action", "/api/machines/nas/skip-next"),
        ("switch.homelab_skip_next_scheduled_action", "/api/clusters/homelab/skip-next"),
    ],
)
async def test_skip_and_unskip(hass, daemon, config_entry, aioclient_mock, entity_id, path):
    daemon.clusters[0]["next_action"] = dict(NEXT)
    daemon.mock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # What the daemon reports on the refresh after skipping (mock() resets all responses,
    # so the skip-next ones are registered after it).
    daemon.machines[0]["next_action"]["will_be_skipped"] = True
    daemon.clusters[0]["next_action"]["will_be_skipped"] = True
    daemon.mock()
    aioclient_mock.post(f"{URL}{path}", json={**NEXT, "will_be_skipped": True})
    aioclient_mock.delete(f"{URL}{path}", json=NEXT)

    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    assert _requests(aioclient_mock, "POST") == [f"{URL}{path}"]
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    assert _requests(aioclient_mock, "DELETE") == [f"{URL}{path}"]


async def test_skip_with_nothing_scheduled_shows_the_reason(hass, setup_integration, aioclient_mock):
    aioclient_mock.post(
        f"{URL}/api/machines/nas/skip-next", status=409, json={"error": "'NAS' has no scheduled run coming up"}
    )
    with pytest.raises(HomeAssistantError, match="no scheduled run"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.nas_skip_next_scheduled_action"}, blocking=True
        )


async def test_switch_turns_off_once_the_skipped_run_has_passed(hass, setup_integration, daemon):
    daemon.machines[0]["next_action"]["will_be_skipped"] = True
    daemon.mock()
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.nas_skip_next_scheduled_action").state == STATE_ON

    daemon.machines[0]["next_action"] = {**NEXT, "time": "2026-10-12T23:00:00+02:00"}
    daemon.mock()
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("switch.nas_skip_next_scheduled_action")
    assert state.state == STATE_OFF
    assert state.attributes["time"] == "2026-10-12T23:00:00+02:00"


async def test_new_rule_makes_switch_available(hass, setup_integration, daemon):
    daemon.machines[1]["next_action"] = dict(NEXT)
    daemon.mock()
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.tv_skip_next_scheduled_action").state == STATE_OFF


async def test_read_only_key_has_no_skip_switch(hass, daemon, config_entry):
    daemon.info["access"] = "read"
    daemon.mock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.nas_skip_next_scheduled_action") is None
