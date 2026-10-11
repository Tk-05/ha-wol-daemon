"""Last and next action of machines and clusters, and the state of clusters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator
from .entity import ClusterEntity, MachineEntity, add_entities_for_new_items

PARALLEL_UPDATES = 0

CLUSTER_STATES = ["on", "off", "partial"]


@dataclass(frozen=True, kw_only=True)
class WolSensorDescription(SensorEntityDescription):
    """value_fn and attributes_fn get the machine's or cluster's JSON from the API."""

    value_fn: Callable[[dict[str, Any]], Any]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any] | None] = lambda item: None


def _time(entry: dict[str, Any] | None) -> datetime | None:
    return dt_util.parse_datetime(entry["time"]) if entry else None


def _last_action_attributes(item: dict[str, Any]) -> dict[str, Any] | None:
    last = item["last_action"]
    if last is None:
        return None
    return {key: last[key] for key in ("action", "source", "result", "detail")}


def _next_action_attributes(item: dict[str, Any]) -> dict[str, Any] | None:
    upcoming = item["next_action"]
    if upcoming is None:
        return None
    return {"rule": upcoming["rule"], "action": upcoming["action"], "will_be_skipped": upcoming["will_be_skipped"]}


LAST_ACTION = WolSensorDescription(
    key="last_action",
    translation_key="last_action",
    device_class=SensorDeviceClass.TIMESTAMP,
    value_fn=lambda item: _time(item["last_action"]),
    attributes_fn=_last_action_attributes,
)
NEXT_ACTION = WolSensorDescription(
    key="next_action",
    translation_key="next_action",
    device_class=SensorDeviceClass.TIMESTAMP,
    value_fn=lambda item: _time(item["next_action"]),
    attributes_fn=_next_action_attributes,
)
CLUSTER_SENSORS = (
    WolSensorDescription(
        key="state",
        translation_key="cluster_state",
        device_class=SensorDeviceClass.ENUM,
        options=CLUSTER_STATES,
        value_fn=lambda cluster: cluster["state"],
    ),
    WolSensorDescription(
        key="members_online",
        translation_key="members_online",
        value_fn=lambda cluster: cluster["online"],
        attributes_fn=lambda cluster: {
            "total": cluster["total"],
            "members": {member["name"]: member["online"] for member in cluster["members"]},
        },
    ),
    LAST_ACTION,
    NEXT_ACTION,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WolDaemonConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    add_entities_for_new_items(
        entry,
        async_add_entities,
        machine_entities=lambda coordinator, key: [
            MachineSensor(coordinator, key, description) for description in (LAST_ACTION, NEXT_ACTION)
        ],
        cluster_entities=lambda coordinator, key: [
            ClusterSensor(coordinator, key, description) for description in CLUSTER_SENSORS
        ],
    )


class MachineSensor(MachineEntity, SensorEntity):
    entity_description: WolSensorDescription

    def __init__(self, coordinator: WolDaemonCoordinator, key: str, description: WolSensorDescription) -> None:
        super().__init__(coordinator, key, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.machine)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attributes_fn(self.machine)


class ClusterSensor(ClusterEntity, SensorEntity):
    entity_description: WolSensorDescription

    def __init__(self, coordinator: WolDaemonCoordinator, key: str, description: WolSensorDescription) -> None:
        super().__init__(coordinator, key, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.cluster)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attributes_fn(self.cluster)
