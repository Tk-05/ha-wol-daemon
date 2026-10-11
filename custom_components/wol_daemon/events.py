"""Listens to the daemon's /api/events stream and refreshes right away when something
changes, on top of the regular polling (which still catches machines switched by hand)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .api import WolDaemonAuthError, WolDaemonError, WolDaemonEventsUnsupported
from .const import EVENTS_RETRY_MAX, EVENTS_RETRY_MIN

if TYPE_CHECKING:
    from .coordinator import WolDaemonCoordinator

_LOGGER = logging.getLogger(__name__)


class EventListener:
    def __init__(self, coordinator: WolDaemonCoordinator) -> None:
        self._coordinator = coordinator
        self.connected = False

    async def run(self) -> None:
        """Runs until the entry is unloaded (which cancels it), reconnecting as needed."""
        retry = EVENTS_RETRY_MIN
        reconnecting = False
        while True:
            try:
                async for event in self._coordinator.client.events():
                    if event.get("type") == "hello":
                        self.connected = True
                        retry = EVENTS_RETRY_MIN
                        if not reconnecting:
                            continue  # just set up; the data is fresh
                    # A change, or a reconnect after which events may have been missed.
                    await self._coordinator.async_request_refresh()
            except WolDaemonEventsUnsupported:
                _LOGGER.info("This WOL Daemon version has no event stream, only polling is used")
                return
            except WolDaemonAuthError:
                # Polling notices too and asks for a new key; the entry is reloaded then.
                return
            except WolDaemonError as err:
                _LOGGER.debug("%s, reconnecting in %d s", err, retry)
            finally:
                self.connected = False
            reconnecting = True
            await asyncio.sleep(retry)
            retry = min(retry * 2, EVENTS_RETRY_MAX)
