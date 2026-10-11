"""Constants for the WOL Daemon integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "wol_daemon"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10

# How long a power switch shows the state it was switched to while the machine is still
# booting or shutting down (a wake-up is verified and retried by the daemon for minutes).
PENDING_STATE_DURATION = timedelta(minutes=5)

# The daemon pings every machine on each status request; it needs up to
# status_timeout_seconds (from /api/info) for an offline one, plus this margin.
REQUEST_TIMEOUT_MARGIN = 10

# The daemon sends a keepalive every 15 s on /api/events; silence for longer than this means
# the connection is dead.
EVENTS_READ_TIMEOUT = 45
# Waits between reconnect attempts to /api/events, doubling up to the maximum.
EVENTS_RETRY_MIN = 5
EVENTS_RETRY_MAX = 300
