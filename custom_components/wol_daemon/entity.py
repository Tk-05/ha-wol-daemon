"""Base entities: one device per machine and per cluster, below a device for the daemon."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import WolDaemonActionError, WolDaemonAuthError, WolDaemonError
from .const import DOMAIN
from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator


def hub_identifier(instance_id: str) -> tuple[str, str]:
    return (DOMAIN, instance_id)


def machine_identifier(instance_id: str, key: str) -> tuple[str, str]:
    return (DOMAIN, f"{instance_id}-machine-{key}")


def cluster_identifier(instance_id: str, key: str) -> tuple[str, str]:
    return (DOMAIN, f"{instance_id}-cluster-{key}")


class WolDaemonEntity(CoordinatorEntity[WolDaemonCoordinator]):
    _attr_has_entity_name = True

    async def _run_action(self, call) -> None:
        """Runs an API action, turning its failure into an error HA shows the user."""
        try:
            await call()
        except WolDaemonAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"WOL Daemon rejected the API key: {err}") from err
        except WolDaemonActionError as err:
            raise HomeAssistantError(f"WOL Daemon: {err}") from err
        except WolDaemonError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.coordinator.async_request_refresh()


class MachineEntity(WolDaemonEntity):
    def __init__(self, coordinator: WolDaemonCoordinator, key: str, suffix: str) -> None:
        super().__init__(coordinator)
        self.machine_key = key
        instance_id = coordinator.info.instance_id
        self._attr_unique_id = f"{instance_id}-machine-{key}-{suffix}"
        machine = coordinator.data.machines[key]
        self._attr_device_info = DeviceInfo(
            identifiers={machine_identifier(instance_id, key)},
            # Merges this device with the same machine from other integrations (e.g. a router).
            connections={(CONNECTION_NETWORK_MAC, machine["mac_address"].lower())},
            name=machine["name"],
            via_device=hub_identifier(instance_id),
            configuration_url=f"{coordinator.client.url}/machines/{key}",
        )

    @property
    def machine(self) -> dict[str, Any]:
        return self.coordinator.data.machines[self.machine_key]

    @property
    def available(self) -> bool:
        return super().available and self.machine_key in self.coordinator.data.machines


class ClusterEntity(WolDaemonEntity):
    def __init__(self, coordinator: WolDaemonCoordinator, key: str, suffix: str) -> None:
        super().__init__(coordinator)
        self.cluster_key = key
        instance_id = coordinator.info.instance_id
        self._attr_unique_id = f"{instance_id}-cluster-{key}-{suffix}"
        cluster = coordinator.data.clusters[key]
        self._attr_device_info = DeviceInfo(
            identifiers={cluster_identifier(instance_id, key)},
            name=cluster["name"],
            model="Cluster",
            via_device=hub_identifier(instance_id),
            configuration_url=f"{coordinator.client.url}/clusters/{key}",
        )

    @property
    def cluster(self) -> dict[str, Any]:
        return self.coordinator.data.clusters[self.cluster_key]

    @property
    def available(self) -> bool:
        return super().available and self.cluster_key in self.coordinator.data.clusters


def add_entities_for_new_items(
    entry: WolDaemonConfigEntry,
    async_add_entities: Callable[[Iterable[Entity]], None],
    machine_entities: Callable[[WolDaemonCoordinator, str], Iterable[Entity]] | None = None,
    cluster_entities: Callable[[WolDaemonCoordinator, str], Iterable[Entity]] | None = None,
) -> None:
    """Adds entities now, and again whenever a machine or cluster shows up in the daemon."""
    coordinator = entry.runtime_data
    known_machines: set[str] = set()
    known_clusters: set[str] = set()

    def add_new() -> None:
        # Gone ones are forgotten, so they get entities again if they come back (their
        # devices are removed in the meantime, see __init__.remove_stale_devices).
        known_machines.intersection_update(coordinator.data.machines)
        known_clusters.intersection_update(coordinator.data.clusters)
        new: list[Entity] = []
        if machine_entities is not None:
            for key in coordinator.data.machines.keys() - known_machines:
                known_machines.add(key)
                new.extend(machine_entities(coordinator, key))
        if cluster_entities is not None:
            for key in coordinator.data.clusters.keys() - known_clusters:
                known_clusters.add(key)
                new.extend(cluster_entities(coordinator, key))
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))
