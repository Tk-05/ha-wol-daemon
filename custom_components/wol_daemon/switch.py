"""Power switch per machine that can be shut down; only with a Control API key.

Waking or shutting down takes minutes, so after switching it shows the requested state
until the machine gets there (or PENDING_STATE_DURATION passes), instead of jumping back
on the next poll."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import PENDING_STATE_DURATION
from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator
from .entity import MachineEntity, add_entities_for_new_items

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WolDaemonConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if not entry.runtime_data.info.can_control:
        return

    def power_switch(coordinator: WolDaemonCoordinator, key: str) -> list[SwitchEntity]:
        # A wake-only machine can't be switched off; it gets just the wake button.
        if coordinator.data.machines[key]["shutdown_method"] == "none":
            return []
        return [MachinePowerSwitch(coordinator, key)]

    add_entities_for_new_items(entry, async_add_entities, machine_entities=power_switch)


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
