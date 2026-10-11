"""Switches, only with a Control API key: power per machine that can be shut down, and
"skip next scheduled action" per machine and cluster.

Waking or shutting down takes minutes, so after switching, the power switch shows the
requested state until the machine gets there (or PENDING_STATE_DURATION passes), instead
of jumping back on the next poll."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import PENDING_STATE_DURATION
from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator
from .entity import ClusterEntity, MachineEntity, add_entities_for_new_items

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WolDaemonConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if not entry.runtime_data.info.can_control:
        return

    def machine_switches(coordinator: WolDaemonCoordinator, key: str) -> list[SwitchEntity]:
        switches: list[SwitchEntity] = [MachineSkipNextSwitch(coordinator, key)]
        # A wake-only machine can't be switched off; it gets just the wake button.
        if coordinator.data.machines[key]["shutdown_method"] != "none":
            switches.append(MachinePowerSwitch(coordinator, key))
        return switches

    add_entities_for_new_items(
        entry,
        async_add_entities,
        machine_entities=machine_switches,
        cluster_entities=lambda coordinator, key: [ClusterSkipNextSwitch(coordinator, key)],
    )


class MachinePowerSwitch(MachineEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "power"

    def __init__(self, coordinator: WolDaemonCoordinator, key: str) -> None:
        super().__init__(coordinator, key, "power")
        self._pending: tuple[bool, datetime] | None = None  # (requested state, until)

    def _pending_state(self) -> bool | None:
        if self._pending is None:
            return None
        wanted, until = self._pending
        if self.machine["online"] == wanted or dt_util.utcnow() >= until:
            return None
        return wanted

    @property
    def is_on(self) -> bool:
        pending = self._pending_state()
        return self.machine["online"] if pending is None else pending

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"switching": self._pending_state() is not None}

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.machine_key in self.coordinator.data.machines and self._pending_state() is None:
            self._pending = None
        super()._handle_coordinator_update()

    async def _switch(self, wanted: bool) -> None:
        async def call() -> None:
            await self.coordinator.client.machine_action(self.machine_key, "on" if wanted else "off")
            self._pending = (wanted, dt_util.utcnow() + PENDING_STATE_DURATION)
            self.async_write_ha_state()

        await self._run_action(call)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._switch(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._switch(False)


class _SkipNextSwitch:
    """On while the next scheduled run (the one the "next scheduled action" sensor shows) is
    going to be skipped. Once that run's time has passed, the daemon moves on to the
    following run and the switch is off again. Unavailable without any upcoming run.

    Mixed in before MachineEntity/ClusterEntity, which provide owner() and the keys."""

    _attr_translation_key = "skip_next"
    _api_kind: str  # "machines" or "clusters", as in the daemon's API paths

    def owner(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def owner_key(self) -> str:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return super().available and self.owner()["next_action"] is not None

    @property
    def is_on(self) -> bool:
        upcoming = self.owner()["next_action"]
        return bool(upcoming and upcoming["will_be_skipped"])

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        upcoming = self.owner()["next_action"]
        if upcoming is None:
            return None
        return {"rule": upcoming["rule"], "action": upcoming["action"], "time": upcoming["time"]}

    async def _set(self, skip: bool) -> None:
        await self._run_action(lambda: self.coordinator.client.skip_next_run(self._api_kind, self.owner_key, skip))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class MachineSkipNextSwitch(_SkipNextSwitch, MachineEntity, SwitchEntity):
    _api_kind = "machines"

    def __init__(self, coordinator: WolDaemonCoordinator, key: str) -> None:
        super().__init__(coordinator, key, "skip_next")

    def owner(self) -> dict[str, Any]:
        return self.machine

    @property
    def owner_key(self) -> str:
        return self.machine_key


class ClusterSkipNextSwitch(_SkipNextSwitch, ClusterEntity, SwitchEntity):
    _api_kind = "clusters"

    def __init__(self, coordinator: WolDaemonCoordinator, key: str) -> None:
        super().__init__(coordinator, key, "skip_next")

    def owner(self) -> dict[str, Any]:
        return self.cluster

    @property
    def owner_key(self) -> str:
        return self.cluster_key
