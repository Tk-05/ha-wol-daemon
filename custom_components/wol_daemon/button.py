"""Wake, shut down and reboot buttons; only with an API key that has Control access."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator
from .entity import ClusterEntity, MachineEntity, add_entities_for_new_items

PARALLEL_UPDATES = 0

# action -> translation key
MACHINE_BUTTONS = {"on": "wake", "off": "shut_down", "reboot": "reboot"}
CLUSTER_BUTTONS = {"on": "wake_all", "off": "shut_down_all"}


async def async_setup_entry(
    hass: HomeAssistant, entry: WolDaemonConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if not entry.runtime_data.info.can_control:
        return

    def machine_buttons(coordinator: WolDaemonCoordinator, key: str) -> list[ButtonEntity]:
        wake_only = coordinator.data.machines[key]["shutdown_method"] == "none"
        actions = ["on"] if wake_only else list(MACHINE_BUTTONS)
        return [MachineButton(coordinator, key, action) for action in actions]

    add_entities_for_new_items(
        entry,
        async_add_entities,
        machine_entities=machine_buttons,
        cluster_entities=lambda coordinator, key: [
            ClusterButton(coordinator, key, action) for action in CLUSTER_BUTTONS
        ],
    )


class MachineButton(MachineEntity, ButtonEntity):
    def __init__(self, coordinator: WolDaemonCoordinator, key: str, action: str) -> None:
        super().__init__(coordinator, key, MACHINE_BUTTONS[action])
        self._action = action
        self._attr_translation_key = MACHINE_BUTTONS[action]
        if action == "reboot":
            self._attr_device_class = ButtonDeviceClass.RESTART

    async def async_press(self) -> None:
        await self._run_action(lambda: self.coordinator.client.machine_action(self.machine_key, self._action))


class ClusterButton(ClusterEntity, ButtonEntity):
    def __init__(self, coordinator: WolDaemonCoordinator, key: str, action: str) -> None:
        super().__init__(coordinator, key, CLUSTER_BUTTONS[action])
        self._action = action
        self._attr_translation_key = CLUSTER_BUTTONS[action]

    async def async_press(self) -> None:
        await self._run_action(lambda: self.coordinator.client.cluster_action(self.cluster_key, self._action))
