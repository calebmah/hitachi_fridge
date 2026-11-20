"""The Hitachi Fridge integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HitachiAuthError, HitachiCloudApiClient, HitachiFridgeError
from .const import (
    CONF_CLOUD_SCAN_INTERVAL,
    CONF_DEVICES,
    CONF_EMAIL,
    CONF_LOCAL_SCAN_INTERVAL,
    CONF_PASSWORD,
    CONF_STATIC_IPS,
    DEFAULT_CLOUD_SCAN_INTERVAL,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HitachiFridgeCoordinator
from .models import ApplianceDevice, CloudSessionData
from .udp import HitachiSharedUdpManager

_LOGGER = logging.getLogger(__name__)

UDP_MANAGER_KEY = "udp_manager"


@dataclass(slots=True)
class HitachiFridgeRuntimeData:
    """Runtime objects stored on `ConfigEntry.runtime_data`."""

    cloud_api: HitachiCloudApiClient
    coordinators: dict[str, HitachiFridgeCoordinator]
    last_options: dict[str, Any] = field(default_factory=dict)


type HitachiFridgeConfigEntry = ConfigEntry[HitachiFridgeRuntimeData]


def _get_shared_udp_manager(hass: HomeAssistant) -> HitachiSharedUdpManager:
    """Return or create the singleton UDP port 50000 manager on `hass.data`."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if UDP_MANAGER_KEY not in domain_data:
        domain_data[UDP_MANAGER_KEY] = HitachiSharedUdpManager()
    return domain_data[UDP_MANAGER_KEY]


async def async_setup_entry(
    hass: HomeAssistant, entry: HitachiFridgeConfigEntry
) -> bool:
    """Set up Hitachi Fridge from a config entry."""
    http_session = async_get_clientsession(hass)
    udp_manager = _get_shared_udp_manager(hass)
    await udp_manager.async_acquire()

    coordinators: dict[str, HitachiFridgeCoordinator] = {}

    @callback
    def _handle_session_renewed(
        new_session: CloudSessionData, refreshed_devices: list[ApplianceDevice]
    ) -> None:
        """Persist automatically renewed Cloud and Local UDP keys into `ConfigEntry.data`."""
        prev_devices_raw = entry.data.get(CONF_DEVICES, [])
        prev_ips: dict[str, str | None] = {}
        for item in prev_devices_raw:
            if isinstance(item, dict) and item.get("dst"):
                prev_ips[str(item["dst"])] = item.get("fridge_ip")

        merged_devices: list[dict[str, Any]] = []
        for dev in refreshed_devices:
            if not dev.fridge_ip and prev_ips.get(dev.dst):
                dev.fridge_ip = prev_ips[dev.dst]
            merged_devices.append(dev.to_config_dict())
            if dev.dst in coordinators:
                coordinators[dev.dst].update_appliance_credentials(dev)

        new_data: dict[str, Any] = {
            **entry.data,
            **new_session.to_config_dict(),
        }
        if merged_devices:
            new_data[CONF_DEVICES] = merged_devices

        new_title: str | None = None
        if (
            len(refreshed_devices) == 1
            and len(entry.title) == 24
            and all(ch in "0123456789ABCDEFabcdef" for ch in entry.title)
        ):
            new_title = refreshed_devices[0].nickname

        if new_title:
            hass.config_entries.async_update_entry(
                entry, title=new_title, data=new_data
            )
        else:
            hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.debug(
            "Persisted renewed Hitachi Fridge session and UDP keys for entry %s",
            entry.entry_id,
        )

    @callback
    def _handle_ip_discovered(dst: str, discovered_ip: str) -> None:
        """Persist newly discovered refrigerator LAN IP into `ConfigEntry.data`."""
        updated_devices: list[dict[str, Any]] = []
        changed = False
        for item in entry.data.get(CONF_DEVICES, []):
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            if copied.get("dst") == dst and copied.get("fridge_ip") != discovered_ip:
                copied["fridge_ip"] = discovered_ip
                changed = True
            updated_devices.append(copied)

        if changed:
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_DEVICES: updated_devices},
            )

    session_data = CloudSessionData.from_config_dict(dict(entry.data))
    cloud_api = HitachiCloudApiClient(
        http_session=http_session,
        email=entry.data.get(CONF_EMAIL),
        password=entry.data.get(CONF_PASSWORD),
        session_data=session_data,
        on_session_renewed=_handle_session_renewed,
    )

    raw_devices = entry.data.get(CONF_DEVICES) or []
    appliances: list[ApplianceDevice] = [
        ApplianceDevice.from_config_dict(item)
        for item in raw_devices
        if isinstance(item, dict) and item.get("dst") and item.get("src")
    ]

    # Bootstrap or self-heal if device list / UDP keys are missing or had swapped columns
    needs_bootstrap = not appliances or any(
        not app.device_key_hex
        or (
            len(app.nickname) == 24
            and all(ch in "0123456789ABCDEFabcdef" for ch in app.nickname)
        )
        for app in appliances
    )
    if needs_bootstrap:
        try:
            appliances = await cloud_api.async_renew_session()
        except HitachiAuthError as err:
            await udp_manager.async_release()
            raise ConfigEntryAuthFailed(
                f"Hitachi Fridge sign-in failed: {err}"
            ) from err
        except HitachiFridgeError as err:
            await udp_manager.async_release()
            raise ConfigEntryNotReady(
                f"Unable to reach Hitachi Cloud during setup: {err}"
            ) from err

    if not appliances:
        await udp_manager.async_release()
        raise ConfigEntryNotReady(
            "No paired Hitachi refrigerators were found on this account."
        )

    local_interval = int(
        entry.options.get(CONF_LOCAL_SCAN_INTERVAL, DEFAULT_LOCAL_SCAN_INTERVAL)
    )
    cloud_interval = int(
        entry.options.get(CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL)
    )
    static_ips: dict[str, str] = dict(entry.options.get(CONF_STATIC_IPS) or {})

    for appliance in appliances:
        static_ip = (static_ips.get(appliance.dst) or "").strip() or None
        coord = HitachiFridgeCoordinator(
            hass=hass,
            config_entry=entry,
            appliance=appliance,
            cloud_api=cloud_api,
            udp_manager=udp_manager,
            local_scan_interval=local_interval,
            cloud_scan_interval=cloud_interval,
            static_ip_override=static_ip,
            on_ip_discovered=_handle_ip_discovered,
        )
        coordinators[appliance.dst] = coord

    try:
        for coord in coordinators.values():
            await coord.async_config_entry_first_refresh()
    except Exception:
        await udp_manager.async_release()
        raise

    entry.runtime_data = HitachiFridgeRuntimeData(
        cloud_api=cloud_api,
        coordinators=coordinators,
        last_options=dict(entry.options),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: HitachiFridgeConfigEntry
) -> None:
    """Apply updated user-facing `options` live without unloading/reloading entities."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return
    new_options = dict(entry.options)
    if new_options == runtime_data.last_options:
        return

    runtime_data.last_options = new_options
    local_interval = int(
        new_options.get(CONF_LOCAL_SCAN_INTERVAL, DEFAULT_LOCAL_SCAN_INTERVAL)
    )
    cloud_interval = int(
        new_options.get(CONF_CLOUD_SCAN_INTERVAL, DEFAULT_CLOUD_SCAN_INTERVAL)
    )
    static_ips: dict[str, str] = dict(new_options.get(CONF_STATIC_IPS) or {})

    for dst, coord in runtime_data.coordinators.items():
        static_ip = (static_ips.get(dst) or "").strip() or None
        if coord.apply_options(local_interval, cloud_interval, static_ip):
            await coord.async_request_refresh()


async def async_unload_entry(
    hass: HomeAssistant, entry: HitachiFridgeConfigEntry
) -> bool:
    """Unload a Hitachi Fridge config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        udp_manager = _get_shared_udp_manager(hass)
        await udp_manager.async_release()
    return unload_ok
