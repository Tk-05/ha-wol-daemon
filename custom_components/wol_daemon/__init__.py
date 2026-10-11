"""The WOL Daemon integration: machines and clusters of a WOL Daemon (Tk-05/WOL)."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WolDaemonAuthError, WolDaemonClient, WolDaemonError
from .coordinator import WolDaemonConfigEntry, WolDaemonCoordinator
from .entity import cluster_identifier, hub_identifier, machine_identifier

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: WolDaemonConfigEntry) -> bool:
    client = WolDaemonClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY])
    try:
        info = await client.get_info()
    except WolDaemonAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except WolDaemonError as err:
        raise ConfigEntryNotReady(str(err)) from err
    client.set_status_timeout(info.status_timeout_seconds)

    coordinator = WolDaemonCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={hub_identifier(info.instance_id)},
        name="WOL Daemon",
        manufacturer="WOL Daemon",
        model="Daemon",
        configuration_url=client.url,
    )
    remove_stale_devices(hass, entry)
    entry.async_on_unload(coordinator.async_add_listener(lambda: remove_stale_devices(hass, entry)))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WolDaemonConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _current_identifiers(entry: WolDaemonConfigEntry) -> set[tuple[str, str]]:
    coordinator = entry.runtime_data
    instance_id = coordinator.info.instance_id
    return {
        hub_identifier(instance_id),
        *(machine_identifier(instance_id, key) for key in coordinator.data.machines),
        *(cluster_identifier(instance_id, key) for key in coordinator.data.clusters),
    }


@callback
def remove_stale_devices(hass: HomeAssistant, entry: WolDaemonConfigEntry) -> None:
    """Removes the devices of machines and clusters that were deleted in the daemon. A failed
    poll keeps the previous data, so an outage doesn't remove anything."""
    current = _current_identifiers(entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & current:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: WolDaemonConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Lets the user delete a device by hand, but only once it's gone from the daemon."""
    return not device.identifiers & _current_identifiers(entry)
