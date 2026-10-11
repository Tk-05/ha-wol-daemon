"""Polls the daemon for the status of all machines and clusters."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DaemonInfo, WolDaemonAuthError, WolDaemonClient, WolDaemonError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .events import EventListener

_LOGGER = logging.getLogger(__name__)

type WolDaemonConfigEntry = ConfigEntry[WolDaemonCoordinator]


@dataclass
class WolDaemonData:
    machines: dict[str, dict[str, Any]] = field(default_factory=dict)
    clusters: dict[str, dict[str, Any]] = field(default_factory=dict)


class WolDaemonCoordinator(DataUpdateCoordinator[WolDaemonData]):
    config_entry: WolDaemonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: WolDaemonConfigEntry,
        client: WolDaemonClient,
        info: DaemonInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self.info = info
        self.event_listener = EventListener(self)

    async def _async_update_data(self) -> WolDaemonData:
        try:
            machines, clusters = await asyncio.gather(self.client.get_machines(), self.client.get_clusters())
        except WolDaemonAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WolDaemonError as err:
            raise UpdateFailed(str(err)) from err
        return WolDaemonData(
            machines={m["key"]: m for m in machines},
            clusters={c["key"]: c for c in clusters},
        )
