"""Diagnostics download, without the API key or network addresses."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import WolDaemonConfigEntry

TO_REDACT = {CONF_API_KEY, "ip_address", "mac_address"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: WolDaemonConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data({"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT),
        "info": asdict(coordinator.info),
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }
