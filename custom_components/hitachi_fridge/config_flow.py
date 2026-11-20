"""Config flow and Options flow for the Hitachi Fridge integration."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    HitachiAuthError,
    HitachiCloudApiClient,
    HitachiConnectionError,
    HitachiFridgeError,
    HitachiTermsNotAcceptedError,
)
from .const import (
    CONF_CLOUD_SCAN_INTERVAL,
    CONF_DEVICES,
    CONF_EMAIL,
    CONF_FRIDGE_IP,
    CONF_LOCAL_SCAN_INTERVAL,
    CONF_PASSWORD,
    CONF_STATIC_IPS,
    DEFAULT_CLOUD_SCAN_INTERVAL,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DOMAIN,
    MAX_CLOUD_SCAN_INTERVAL,
    MAX_LOCAL_SCAN_INTERVAL,
    MIN_CLOUD_SCAN_INTERVAL,
    MIN_LOCAL_SCAN_INTERVAL,
)
from .models import ApplianceDevice, CloudSessionData
from .udp import HitachiApplianceLocalClient, HitachiSharedUdpManager

_LOGGER = logging.getLogger(__name__)


def _is_valid_ipv4(value: str) -> bool:
    """Return True if `value` is a valid IPv4 address."""
    try:
        ip_obj = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return isinstance(ip_obj, ipaddress.IPv4Address)


class HitachiFridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hitachi Fridge."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HitachiFridgeOptionsFlow:
        """Create the options flow handler."""
        return HitachiFridgeOptionsFlow(config_entry)

    async def _async_authenticate_and_discover(
        self,
        email: str,
        password: str,
        static_ip_hint: str | None = None,
    ) -> tuple[CloudSessionData, list[ApplianceDevice]]:
        """Sign in to Hitachi Account Cloud, list paired fridges, and probe LAN UDP."""
        http_session = async_get_clientsession(self.hass)
        api = HitachiCloudApiClient(http_session=http_session)
        session = await api.async_login(email=email, password=password)
        devices = await api.async_get_devices()
        if not devices:
            return session, []

        if static_ip_hint and len(devices) == 1:
            devices[0].fridge_ip = static_ip_hint
            return session, devices

        # Best-effort non-blocking Local UDP broadcast discovery during setup
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        udp_manager: HitachiSharedUdpManager | None = domain_data.get("udp_manager")
        temp_manager: HitachiSharedUdpManager | None = None
        if udp_manager is None:
            temp_manager = HitachiSharedUdpManager()
            udp_manager = temp_manager

        acquired = await udp_manager.async_acquire()
        try:
            if acquired:
                for dev in devices:
                    if static_ip_hint and not dev.fridge_ip and len(devices) == 1:
                        dev.fridge_ip = static_ip_hint
                        continue
                    local_client = HitachiApplianceLocalClient(udp_manager, dev)
                    try:
                        await local_client.async_discover_ip(timeout=1.5)
                    except (TimeoutError, OSError, RuntimeError):
                        pass
        finally:
            await udp_manager.async_release()

        return session, devices

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial Hitachi Fridge account sign-in."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = str(user_input[CONF_EMAIL]).strip()
            password = str(user_input[CONF_PASSWORD])
            raw_ip = str(user_input.get(CONF_FRIDGE_IP) or "").strip()

            if raw_ip and not _is_valid_ipv4(raw_ip):
                errors[CONF_FRIDGE_IP] = "invalid_ip"
            else:
                try:
                    session, devices = await self._async_authenticate_and_discover(
                        email=email,
                        password=password,
                        static_ip_hint=raw_ip or None,
                    )
                except HitachiTermsNotAcceptedError:
                    errors["base"] = "terms_not_accepted"
                except HitachiAuthError:
                    errors["base"] = "invalid_auth"
                except HitachiConnectionError:
                    errors["base"] = "cannot_connect"
                except HitachiFridgeError:
                    errors["base"] = "unknown"
                except Exception:
                    _LOGGER.exception("Unexpected error during Hitachi Fridge sign-in")
                    errors["base"] = "unknown"
                else:
                    if not devices:
                        errors["base"] = "no_devices_found"
                    else:
                        await self.async_set_unique_id(session.cspf_id.lower())
                        self._abort_if_unique_id_configured()

                        entry_data: dict[str, Any] = {
                            CONF_EMAIL: email,
                            CONF_PASSWORD: password,
                            **session.to_config_dict(),
                            CONF_DEVICES: [dev.to_config_dict() for dev in devices],
                        }
                        options: dict[str, Any] = {}
                        if raw_ip and len(devices) == 1:
                            options[CONF_STATIC_IPS] = {devices[0].dst: raw_ip}

                        title = (
                            devices[0].nickname
                            if len(devices) == 1
                            else f"Hitachi Fridge ({email})"
                        )
                        return self.async_create_entry(
                            title=title,
                            data=entry_data,
                            options=options,
                        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_EMAIL,
                    default=(user_input or {}).get(CONF_EMAIL, ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_FRIDGE_IP,
                    default=(user_input or {}).get(CONF_FRIDGE_IP, ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Initiate reauthentication when stored Hitachi account credentials fail."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication password prompt."""
        reauth_entry = self._get_reauth_entry()
        existing_email = str(reauth_entry.data.get(CONF_EMAIL) or "")
        errors: dict[str, str] = {}

        if user_input is not None:
            email = str(user_input.get(CONF_EMAIL) or existing_email).strip()
            password = str(user_input[CONF_PASSWORD])
            try:
                session, devices = await self._async_authenticate_and_discover(
                    email=email,
                    password=password,
                )
            except HitachiTermsNotAcceptedError:
                errors["base"] = "terms_not_accepted"
            except HitachiAuthError:
                errors["base"] = "invalid_auth"
            except HitachiConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Hitachi Fridge reauth")
                errors["base"] = "unknown"
            else:
                prev_ips = {
                    str(item["dst"]): item.get("fridge_ip")
                    for item in reauth_entry.data.get(CONF_DEVICES, [])
                    if isinstance(item, dict) and item.get("dst")
                }
                for dev in devices:
                    if not dev.fridge_ip and prev_ips.get(dev.dst):
                        dev.fridge_ip = prev_ips[dev.dst]

                updated_data: dict[str, Any] = {
                    **reauth_entry.data,
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                    **session.to_config_dict(),
                }
                if devices:
                    updated_data[CONF_DEVICES] = [d.to_config_dict() for d in devices]

                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates=updated_data,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=existing_email): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.EMAIL)
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            description_placeholders={"email": existing_email},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow updating Hitachi account credentials from the integration menu."""
        reconfig_entry = self._get_reconfigure_entry()
        existing_email = str(reconfig_entry.data.get(CONF_EMAIL) or "")
        errors: dict[str, str] = {}

        if user_input is not None:
            email = str(user_input[CONF_EMAIL]).strip()
            password = str(user_input[CONF_PASSWORD])
            try:
                session, devices = await self._async_authenticate_and_discover(
                    email=email,
                    password=password,
                )
            except HitachiTermsNotAcceptedError:
                errors["base"] = "terms_not_accepted"
            except HitachiAuthError:
                errors["base"] = "invalid_auth"
            except HitachiConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Hitachi Fridge reconfigure")
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices_found"
                else:
                    await self.async_set_unique_id(session.cspf_id.lower())
                    self._abort_if_unique_id_mismatch()

                    prev_ips = {
                        str(item["dst"]): item.get("fridge_ip")
                        for item in reconfig_entry.data.get(CONF_DEVICES, [])
                        if isinstance(item, dict) and item.get("dst")
                    }
                    for dev in devices:
                        if not dev.fridge_ip and prev_ips.get(dev.dst):
                            dev.fridge_ip = prev_ips[dev.dst]

                    updated_data: dict[str, Any] = {
                        **reconfig_entry.data,
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        **session.to_config_dict(),
                        CONF_DEVICES: [d.to_config_dict() for d in devices],
                    }
                    return self.async_update_reload_and_abort(
                        reconfig_entry,
                        data_updates=updated_data,
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=existing_email): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.EMAIL)
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )


class HitachiFridgeOptionsFlow(OptionsFlow):
    """Handle polling interval and per-refrigerator LAN IP options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        raw_devices = [
            ApplianceDevice.from_config_dict(item)
            for item in self._entry.data.get(CONF_DEVICES, [])
            if isinstance(item, dict) and item.get("dst")
        ]
        existing_static_ips: dict[str, str] = dict(
            self._entry.options.get(CONF_STATIC_IPS) or {}
        )

        if user_input is not None:
            new_static_ips: dict[str, str] = {}
            for dev in raw_devices:
                field_key = (
                    CONF_FRIDGE_IP
                    if len(raw_devices) == 1
                    else f"{dev.nickname} LAN IP ({dev.dst[:8]})"
                )
                ip_val = str(user_input.get(field_key) or "").strip()
                if ip_val:
                    if not _is_valid_ipv4(ip_val):
                        errors[field_key] = "invalid_ip"
                    else:
                        new_static_ips[dev.dst] = ip_val

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_LOCAL_SCAN_INTERVAL: int(
                            user_input[CONF_LOCAL_SCAN_INTERVAL]
                        ),
                        CONF_CLOUD_SCAN_INTERVAL: int(
                            user_input[CONF_CLOUD_SCAN_INTERVAL]
                        ),
                        CONF_STATIC_IPS: new_static_ips,
                    },
                )

        fields: dict[Any, Any] = {
            vol.Required(
                CONF_LOCAL_SCAN_INTERVAL,
                default=self._entry.options.get(
                    CONF_LOCAL_SCAN_INTERVAL, DEFAULT_LOCAL_SCAN_INTERVAL
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_LOCAL_SCAN_INTERVAL,
                    max=MAX_LOCAL_SCAN_INTERVAL,
                    step=1,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_CLOUD_SCAN_INTERVAL,
                default=self._entry.options.get(
                    CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_CLOUD_SCAN_INTERVAL,
                    max=MAX_CLOUD_SCAN_INTERVAL,
                    step=5,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }

        for dev in raw_devices:
            field_key = (
                CONF_FRIDGE_IP
                if len(raw_devices) == 1
                else f"{dev.nickname} LAN IP ({dev.dst[:8]})"
            )
            fields[
                vol.Optional(
                    field_key,
                    default=existing_static_ips.get(dev.dst, ""),
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            errors=errors,
        )
