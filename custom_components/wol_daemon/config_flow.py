"""Config flow: the daemon's URL and an API key from its Settings page."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import DaemonInfo, WolDaemonAuthError, WolDaemonClient, WolDaemonError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL
from .coordinator import WolDaemonConfigEntry

_LOGGER = logging.getLogger(__name__)

_URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if "://" in url else f"http://{url}"


def _is_plain_ip_url(url: str) -> bool:
    """http://<IP address>:<port>, as discovery would set it. A hostname or a URL behind a
    reverse proxy was chosen on purpose, and discovery shouldn't overwrite it."""
    parts = urlsplit(url)
    try:
        ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        return False
    return parts.scheme == "http" and parts.path in ("", "/")


class WolDaemonConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    _discovered_url: str

    async def _validate(self, url: str, api_key: str) -> tuple[DaemonInfo | None, dict[str, str]]:
        client = WolDaemonClient(async_get_clientsession(self.hass), url, api_key)
        try:
            return await client.get_info(), {}
        except WolDaemonAuthError:
            return None, {"base": "invalid_auth"}
        except WolDaemonError as err:
            _LOGGER.debug("Can't connect to %s: %s", url, err)
            return None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error talking to %s", url)
            return None, {"base": "unknown"}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            info, errors = await self._validate(url, user_input[CONF_API_KEY])
            if info is not None:
                await self.async_set_unique_id(info.instance_id)
                # Same daemon at a new address: just update it.
                self._abort_if_unique_id_configured(updates={CONF_URL: url})
                return self.async_create_entry(
                    title=f"WOL Daemon ({urlsplit(url).hostname})",
                    data={CONF_URL: url, CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_URL): _URL_SELECTOR, vol.Required(CONF_API_KEY): _KEY_SELECTOR}),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        instance_id = discovery_info.properties.get("id")
        if not instance_id or discovery_info.port is None:
            return self.async_abort(reason="not_wol_daemon")
        url = f"http://{discovery_info.host}:{discovery_info.port}"
        await self.async_set_unique_id(instance_id)
        # Known daemon: follow a changed address, unless the URL was entered as a name.
        existing = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, instance_id)
        follow = existing is not None and _is_plain_ip_url(existing.data[CONF_URL])
        self._abort_if_unique_id_configured(updates={CONF_URL: url} if follow else None)

        self._discovered_url = url
        self.context["title_placeholders"] = {"name": discovery_info.name.removesuffix("." + discovery_info.type)}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        url = self._discovered_url
        if user_input is not None:
            info, errors = await self._validate(url, user_input[CONF_API_KEY])
            if info is not None:
                if info.instance_id != self.unique_id:
                    return self.async_abort(reason="wrong_daemon")
                return self.async_create_entry(
                    title=f"WOL Daemon ({urlsplit(url).hostname})",
                    data={CONF_URL: url, CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _KEY_SELECTOR}),
            description_placeholders={"url": url},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._validate(entry.data[CONF_URL], user_input[CONF_API_KEY])
            if info is not None:
                await self.async_set_unique_id(info.instance_id)
                self._abort_if_unique_id_mismatch(reason="wrong_daemon")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _KEY_SELECTOR}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            info, errors = await self._validate(url, user_input[CONF_API_KEY])
            if info is not None:
                await self.async_set_unique_id(info.instance_id)
                self._abort_if_unique_id_mismatch(reason="wrong_daemon")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_URL: url, CONF_API_KEY: user_input[CONF_API_KEY]}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_URL): _URL_SELECTOR, vol.Required(CONF_API_KEY): _KEY_SELECTOR}),
                user_input or {CONF_URL: entry.data[CONF_URL], CONF_API_KEY: entry.data[CONF_API_KEY]},
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: WolDaemonConfigEntry) -> WolDaemonOptionsFlow:
        return WolDaemonOptionsFlow()


class WolDaemonOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_SCAN_INTERVAL): vol.All(
                            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)
                        ),
                    }
                ),
                {CONF_SCAN_INTERVAL: self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)},
            ),
        )
