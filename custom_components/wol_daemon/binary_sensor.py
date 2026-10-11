"""Whether a machine answers pings."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator
from .entity import MachineEntity, add_entities_for_new_items

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WolDaemonConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    add_entities_for_new_items(
        entry,
        async_add_entities,
        machine_entities=lambda coordinator, key: [MachineOnlineSensor(coordinator, key)],
    )


class MachineOnlineSensor(MachineEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(self, coordinator: WolDaemonCoordinator, key: str) -> None:
        super().__init__(coordinator, key, "online")

    @property
    def is_on(self) -> bool:
        return self.machine["online"]
