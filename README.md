# WOL Daemon for Home Assistant

Home Assistant integration for [WOL Daemon](https://github.com/Tk-05/WOL): every machine
and cluster of the daemon shows up as a device, with its online status, schedule, and
buttons and a switch to wake, shut down and reboot it.

## Requirements

- WOL Daemon with named API keys (Settings → **API keys**) and the `/api/info` endpoint.
- Home Assistant 2025.8 or newer.

## Installation

**HACS**: HACS → ⋮ → *Custom repositories* → add `https://github.com/Tk-05/ha-wol-daemon`
as type *Integration*, then install **WOL Daemon** and restart Home Assistant.

**Manually**: copy `custom_components/wol_daemon` into your Home Assistant
`config/custom_components/` folder and restart.

## Setup

If the daemon is on the same network, Home Assistant finds it by itself: it shows up under
**Settings → Devices & services → Discovered**, and you only need to enter an API key
(step 1). Otherwise:

1. In the daemon's web UI, go to **Settings → API keys** and create a key named e.g.
   "Home Assistant". Pick **Control** access to be able to switch machines from Home
   Assistant; a **Read only** key gives you just the status entities.
2. In Home Assistant: **Settings → Devices & services → Add integration → WOL Daemon**,
   and enter the daemon's URL (e.g. `http://192.168.1.5:9090`) and the key.

The daemon is recognised by its instance ID, so if its address changes, add it again with
the new URL (or use *Reconfigure*): the existing entry is updated instead of duplicated. If
the key is revoked, Home Assistant asks for a new one.

Under *Configure* you can change the polling interval (default 30 seconds). Every poll
makes the daemon ping all machines, so there's no point in going much lower.

## Updates

The integration keeps a connection to the daemon's event stream open, so actions
(from Home Assistant, the daemon's web UI or its schedule), their results and changes to
machines, clusters and schedules show up right away. Polling stays on for the online
status, which also catches machines switched on or off by hand. With an older daemon
without the event stream, everything works by polling alone.

If the daemon's address changes, discovery updates it, as long as it was set up with an
IP address (a host name or reverse-proxy URL is left as entered).

## Entities

**Per machine** (device named like the machine, linked by MAC address to the same device
from other integrations, e.g. your router):

| Entity | |
| --- | --- |
| `binary_sensor.<machine>_online` | answers pings |
| `switch.<machine>_power` | on = wake, off = shut down (*) |
| `button.<machine>_wake` | sends the magic packet |
| `button.<machine>_shut_down`, `button.<machine>_reboot` | via Proxmox or SSH (*) |
| `sensor.<machine>_last_action` | time of the last wake/shutdown; action, source, result and detail as attributes |
| `sensor.<machine>_next_scheduled_action` | time of the next schedule rule; rule, action and whether it will be skipped as attributes |

(*) Only for machines with a shutdown method; wake-only machines just get the wake button.
Switches and buttons need a key with Control access.

Waking or shutting down takes a while, so after switching, the power switch shows the
requested state (attribute `switching: true`) until the machine gets there, for at most
5 minutes, instead of jumping back on the next poll.

**Per cluster**:

| Entity | |
| --- | --- |
| `sensor.<cluster>_state` | `on` (all members online), `off` or `partial` |
| `sensor.<cluster>_machines_online` | number of members online; `total` and each member's status as attributes |
| `button.<cluster>_wake_all`, `button.<cluster>_shut_down_all` | runs the cluster's sequence in the daemon |
| `sensor.<cluster>_last_action`, `sensor.<cluster>_next_scheduled_action` | as for machines |

Machines and clusters added in the daemon appear automatically; deleted ones are removed
from Home Assistant on the next poll.

Actions show up in the daemon's event log with the source `api:<key name>`.

## Releasing

Bump `version` in `custom_components/wol_daemon/manifest.json`, merge, then tag that
commit (`git tag v0.3.0 && git push origin v0.3.0`). The Release workflow checks the tag
against the manifest and publishes the GitHub release that HACS offers as an update.

## Development

```sh
pip install -r requirements_test.txt ruff
python -m pytest
ruff check custom_components tests && ruff format --check custom_components tests
```
