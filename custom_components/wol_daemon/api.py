"""Client for the WOL Daemon JSON API (docs/api.md in Tk-05/WOL)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import EVENTS_READ_TIMEOUT, REQUEST_TIMEOUT_MARGIN


class WolDaemonError(Exception):
    """The daemon couldn't be reached or answered unexpectedly."""


class WolDaemonAuthError(WolDaemonError):
    """The API key is missing, wrong or revoked."""


class WolDaemonActionError(WolDaemonError):
    """The daemon refused or failed an action; the message is its reason."""


class WolDaemonEventsUnsupported(WolDaemonError):
    """The daemon has no /api/events yet (older version); polling still works."""


@dataclass(frozen=True)
class DaemonInfo:
    instance_id: str
    status_timeout_seconds: int
    can_control: bool
    key_name: str | None


class WolDaemonClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = aiohttp.ClientTimeout(total=5 + REQUEST_TIMEOUT_MARGIN)

    @property
    def url(self) -> str:
        return self._url

    def set_status_timeout(self, seconds: int) -> None:
        """Status requests ping machines and can take up to the daemon's ping timeout."""
        self._timeout = aiohttp.ClientTimeout(total=seconds + REQUEST_TIMEOUT_MARGIN)

    async def _request(self, method: str, path: str) -> tuple[int, Any]:
        try:
            async with self._session.request(
                method, self._url + path, headers=self._headers, timeout=self._timeout
            ) as response:
                if response.status == 401:
                    raise WolDaemonAuthError("API key rejected")
                try:
                    body = await response.json(content_type=None)
                except ValueError as err:
                    raise WolDaemonError(f"{path} answered HTTP {response.status} without JSON") from err
                return response.status, body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WolDaemonError(f"Can't reach {self._url}: {err or type(err).__name__}") from err

    async def _get(self, path: str) -> dict[str, Any]:
        status, body = await self._request("GET", path)
        if status != 200:
            raise WolDaemonError(f"{path} answered HTTP {status}: {_error_text(body)}")
        return body

    async def _action(self, path: str, method: str = "POST") -> dict[str, Any] | None:
        status, body = await self._request(method, path)
        if status in (200, 202):
            return body
        raise WolDaemonActionError(_error_text(body))

    async def get_info(self) -> DaemonInfo:
        body = await self._get("/api/info")
        try:
            return DaemonInfo(
                instance_id=body["instance_id"],
                status_timeout_seconds=int(body["status_timeout_seconds"]),
                can_control=body["access"] == "control",
                key_name=body.get("key_name"),
            )
        except (KeyError, TypeError, ValueError) as err:
            # /api/info only exists from the daemon version with control keys on.
            raise WolDaemonError("Unexpected answer from /api/info, is the daemon up to date?") from err

    async def get_machines(self) -> list[dict[str, Any]]:
        return (await self._get("/api/machines"))["machines"]

    async def get_clusters(self) -> list[dict[str, Any]]:
        return (await self._get("/api/clusters"))["clusters"]

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yields the daemon's change notifications (see /api/events) until the stream ends."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=EVENTS_READ_TIMEOUT)
        try:
            async with self._session.get(self._url + "/api/events", headers=self._headers, timeout=timeout) as response:
                if response.status == 401:
                    raise WolDaemonAuthError("API key rejected")
                if response.status == 404:
                    raise WolDaemonEventsUnsupported("The daemon doesn't offer /api/events")
                if response.status != 200:
                    raise WolDaemonError(f"/api/events answered HTTP {response.status}")
                async for raw_line in response.content:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("data:"):
                        try:
                            yield json.loads(line[5:].strip())
                        except ValueError:
                            continue
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WolDaemonError(f"Event stream from {self._url} broke off: {err or type(err).__name__}") from err

    async def machine_action(self, key: str, action: str) -> dict[str, Any] | None:
        """action: on, off or reboot. Returns the recorded action (result ok or skipped)."""
        return await self._action(f"/api/machines/{key}/action/{action}")

    async def cluster_action(self, key: str, action: str) -> dict[str, Any] | None:
        """action: on or off. The daemon runs the sequence in the background."""
        return await self._action(f"/api/clusters/{key}/action/{action}")

    async def skip_next_run(self, kind: str, key: str, skip: bool) -> dict[str, Any] | None:
        """kind: machines or clusters. Skips (or un-skips) the next scheduled run and
        returns the updated next_action."""
        return await self._action(f"/api/{kind}/{key}/skip-next", "POST" if skip else "DELETE")


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        if body.get("error"):
            return str(body["error"])
        if body.get("result") == "error":
            return str(body.get("detail") or "failed")
    return "unexpected answer"
