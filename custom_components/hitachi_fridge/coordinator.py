"""DataUpdateCoordinator for a paired Hitachi Smart Refrigerator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    HitachiAuthError,
    HitachiCloudApiClient,
    HitachiCommandError,
    HitachiConnectionError,
    HitachiFridgeError,
)
from .const import (
    AUX_METADATA_REFRESH_SECONDS,
    CONF_DEVICES,
    DOMAIN,
    LOCAL_REDISCOVERY_CLOUD_CYCLES,
    LOGIN_CHECK_REFRESH_SECONDS,
    POST_CONTROL_DELAY_SECONDS,
    CtrlCode,
    ModelCapabilities,
)
from .models import (
    AlarmHistoryEntry,
    ApplianceDevice,
    DailyDoorStat,
    FirmwareStatus,
    FridgeCoordinatorSnapshot,
    FridgeTelemetry,
)
from .udp import HitachiApplianceLocalClient, HitachiSharedUdpManager

_LOGGER = logging.getLogger(__name__)


class HitachiFridgeCoordinator(DataUpdateCoordinator[FridgeCoordinatorSnapshot]):
    """Coordinator managing Local UDP polling, Cloud fallback, and control commands."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        appliance: ApplianceDevice,
        cloud_api: HitachiCloudApiClient,
        udp_manager: HitachiSharedUdpManager,
        local_scan_interval: int,
        cloud_scan_interval: int,
        static_ip_override: str | None = None,
        on_ip_discovered: Callable[[str, str], None] | None = None,
    ) -> None:
        """Initialize the refrigerator coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{appliance.dst}",
            update_interval=timedelta(seconds=local_scan_interval),
        )
        self.appliance = appliance
        self.cloud_api = cloud_api
        self.local_client = HitachiApplianceLocalClient(udp_manager, appliance)
        self.local_scan_interval = local_scan_interval
        self.cloud_scan_interval = cloud_scan_interval
        self.static_ip_override = static_ip_override
        self._on_ip_discovered = on_ip_discovered

        self._consecutive_udp_failures: int = 0
        self._cloud_cycles_since_udp_probe: int = 0
        self._last_aux_refresh_monotonic: float = 0.0
        self._last_aux_date: date | None = None
        self._last_login_check_monotonic: float = 0.0

        self._cached_door_history: dict[str, DailyDoorStat] = {}
        self._cached_firmware: FirmwareStatus | None = None
        self._cached_alarm_history: list[AlarmHistoryEntry] = []
        self._cached_disabled_push_ids: set[str] | None = None

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return model-specific hardware capabilities."""
        return self.appliance.capabilities

    def update_appliance_credentials(self, refreshed: ApplianceDevice) -> None:
        """Update in-memory `SRC`, `device_key`, `device_iv`, and nickname after renewal."""
        self.appliance.src = refreshed.src
        if refreshed.device_key_hex:
            self.appliance.device_key_hex = refreshed.device_key_hex
        if refreshed.device_iv_hex:
            self.appliance.device_iv_hex = refreshed.device_iv_hex
        if refreshed.nickname:
            self.appliance.nickname = refreshed.nickname

    def apply_options(
        self,
        local_scan_interval: int,
        cloud_scan_interval: int,
        static_ip_override: str | None,
    ) -> bool:
        """Apply updated Options Flow settings live without unloading entities.

        Returns True if the static IP override changed and an immediate refresh is needed.
        """
        ip_changed = static_ip_override != self.static_ip_override
        self.local_scan_interval = local_scan_interval
        self.cloud_scan_interval = cloud_scan_interval
        self.static_ip_override = static_ip_override
        if self.data is not None and self.data.transport == "cloud_http":
            self.update_interval = timedelta(seconds=cloud_scan_interval)
        else:
            self.update_interval = timedelta(seconds=local_scan_interval)
        return ip_changed

    async def _async_try_local_telemetry(self) -> tuple[FridgeTelemetry, str] | None:
        """Attempt to poll `MOVEINF` over Local LAN UDP `:50000`."""
        prev_persisted_ip = self.appliance.fridge_ip
        target_ip = self.static_ip_override or prev_persisted_ip

        # When operating on Cloud fallback without a static IP, periodically re-probe LAN
        if (
            self.data is not None
            and self.data.transport == "cloud_http"
            and not self.static_ip_override
        ):
            self._cloud_cycles_since_udp_probe += 1
            if self._cloud_cycles_since_udp_probe < LOCAL_REDISCOVERY_CLOUD_CYCLES:
                return None
            self._cloud_cycles_since_udp_probe = 0

        try:
            if not target_ip:
                target_ip = await self.local_client.async_discover_ip()
            telemetry, sender_ip = await self.local_client.async_get_telemetry(
                target_ip=target_ip,
                tz=dt_util.DEFAULT_TIME_ZONE,
            )
            self._consecutive_udp_failures = 0
            self._cloud_cycles_since_udp_probe = 0
            if sender_ip != prev_persisted_ip and not self.static_ip_override:
                self.appliance.fridge_ip = sender_ip
                if self._on_ip_discovered is not None:
                    self._on_ip_discovered(self.appliance.dst, sender_ip)
            return telemetry, sender_ip
        except (TimeoutError, OSError, RuntimeError, ValueError) as err:
            self._consecutive_udp_failures += 1
            # Broadcast `SEARCH` once if unicast IP changed via DHCP
            if (
                not self.static_ip_override
                and target_ip is not None
                and self._consecutive_udp_failures == 2
            ):
                try:
                    discovered_ip = await self.local_client.async_discover_ip()
                    telemetry, sender_ip = await self.local_client.async_get_telemetry(
                        target_ip=discovered_ip,
                        tz=dt_util.DEFAULT_TIME_ZONE,
                    )
                    self._consecutive_udp_failures = 0
                    self.appliance.fridge_ip = sender_ip
                    if sender_ip != prev_persisted_ip and self._on_ip_discovered is not None:
                        self._on_ip_discovered(self.appliance.dst, sender_ip)
                    return telemetry, sender_ip
                except (TimeoutError, OSError, RuntimeError, ValueError):
                    pass

            _LOGGER.debug(
                "Local UDP poll for %s failed (%s); falling back to Hitachi Cloud",
                self.appliance.nickname,
                err or type(err).__name__,
            )
            return None

    async def _async_refresh_auxiliary_cloud_data(
        self, *, force: bool = False
    ) -> None:
        """Periodically refresh 10-day door history, firmware info, alarm log, and push settings."""
        now_mono = time.monotonic()
        today = dt_util.now().date()

        # Proactive session check (`CMD=LOGINCHK`) with automatic silent renewal
        if (
            force
            or self._last_login_check_monotonic == 0.0
            or (now_mono - self._last_login_check_monotonic)
            >= LOGIN_CHECK_REFRESH_SECONDS
        ):
            try:
                await self.cloud_api.async_ensure_session_valid()
                self._last_login_check_monotonic = now_mono
            except HitachiAuthError as err:
                raise ConfigEntryAuthFailed(
                    f"Hitachi Fridge authentication failed: {err}"
                ) from err
            except HitachiFridgeError as err:
                _LOGGER.debug("Skipping LOGINCHK due to transient cloud error: %s", err)

        should_refresh_aux = (
            force
            or self._last_aux_refresh_monotonic == 0.0
            or self._last_aux_date != today
            or (now_mono - self._last_aux_refresh_monotonic)
            >= AUX_METADATA_REFRESH_SECONDS
        )
        if not should_refresh_aux:
            return

        self._last_aux_refresh_monotonic = now_mono
        self._last_aux_date = today

        # 1. 10-day door history (`CMD=DELIVERY`)
        try:
            self._cached_door_history = await self.cloud_api.async_get_door_history(
                self.appliance.dst, self.appliance.src
            )
        except HitachiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HitachiFridgeError as err:
            _LOGGER.debug("Door history fetch failed for %s: %s", self.appliance.dst, err)

        # 2. Firmware version & auto-update status (`CMD=FWINFO`)
        try:
            fw_status = await self.cloud_api.async_get_firmware_info(
                self.appliance.dst, self.appliance.src
            )
            if fw_status is not None:
                prev_ver = self._cached_firmware.version if self._cached_firmware else None
                self._cached_firmware = fw_status
                if fw_status.version and fw_status.version != prev_ver:
                    dev_reg = dr.async_get(self.hass)
                    for dev_entry in dr.async_entries_for_config_entry(
                        dev_reg, self.config_entry.entry_id
                    ):
                        if (DOMAIN, self.appliance.dst) in dev_entry.identifiers:
                            dev_reg.async_update_device(
                                dev_entry.id, sw_version=fw_status.version
                            )
                            break
        except HitachiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HitachiFridgeError as err:
            _LOGGER.debug("Firmware info fetch failed for %s: %s", self.appliance.dst, err)

        # 3. Alarm / Notification history (`CMD=HISTORY`)
        try:
            self._cached_alarm_history = await self.cloud_api.async_get_alarm_history(
                self.appliance.dst, self.appliance.src
            )
        except HitachiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HitachiFridgeError as err:
            _LOGGER.debug("Alarm history fetch failed for %s: %s", self.appliance.dst, err)

        # 4. Push notification settings (`CMD=PUSHINF`)
        try:
            self._cached_disabled_push_ids = (
                await self.cloud_api.async_get_disabled_push_notifications(
                    self.appliance.src
                )
            )
        except HitachiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HitachiFridgeError as err:
            _LOGGER.debug("Push notification fetch failed for %s: %s", self.appliance.dst, err)

    async def _async_update_data(self) -> FridgeCoordinatorSnapshot:
        """Fetch latest refrigerator telemetry via Local UDP first, then Cloud HTTP."""
        local_res = await self._async_try_local_telemetry()
        if local_res is not None:
            telemetry, active_ip = local_res
            transport = "local_udp"
            desired_interval = timedelta(seconds=self.local_scan_interval)
        else:
            try:
                telemetry = await self.cloud_api.async_get_telemetry(
                    self.appliance.dst,
                    self.appliance.src,
                    tz=dt_util.DEFAULT_TIME_ZONE,
                )
            except HitachiAuthError as err:
                raise ConfigEntryAuthFailed(
                    f"Hitachi Fridge authentication failed: {err}"
                ) from err
            except HitachiFridgeError as err:
                raise UpdateFailed(
                    f"Unable to reach {self.appliance.nickname} locally or via Hitachi Cloud: {err}"
                ) from err
            active_ip = self.static_ip_override or self.appliance.fridge_ip
            transport = "cloud_http"
            desired_interval = timedelta(seconds=self.cloud_scan_interval)

        if self.update_interval != desired_interval:
            self.update_interval = desired_interval

        await self._async_refresh_auxiliary_cloud_data(force=False)

        # Merge live Today & Yesterday counts/durations into the 10-day history dict
        merged_history = dict(self._cached_door_history)
        today_date = dt_util.now().date()
        yest_date = today_date - timedelta(days=1)
        merged_history[yest_date.isoformat()] = DailyDoorStat(
            stat_date=yest_date,
            door_opens=telemetry.door_opens_yesterday,
            refrigerator_open_seconds=telemetry.door_f_open_seconds_yesterday,
            drawer_open_seconds=telemetry.door_d_open_seconds_yesterday,
        )
        merged_history[today_date.isoformat()] = DailyDoorStat(
            stat_date=today_date,
            door_opens=telemetry.door_opens_today,
            refrigerator_open_seconds=telemetry.door_f_open_seconds_today,
            drawer_open_seconds=telemetry.door_d_open_seconds_today,
        )

        return FridgeCoordinatorSnapshot(
            telemetry=telemetry,
            transport=transport,
            fridge_ip=active_ip,
            nickname=self.appliance.nickname,
            door_history=dict(sorted(merged_history.items())),
            firmware=self._cached_firmware,
            alarm_history=list(self._cached_alarm_history),
            disabled_push_ids=(
                set(self._cached_disabled_push_ids)
                if self._cached_disabled_push_ids is not None
                else None
            ),
        )

    async def async_send_control(
        self, ctrl_code: CtrlCode, raw_value: int
    ) -> None:
        """Send a `CTRLINS` control command via Local UDP first, falling back to Cloud."""
        ctrl_data = f"{raw_value:02X}"
        target_ip = self.static_ip_override or self.appliance.fridge_ip

        sent_locally = False
        if target_ip or self.data is None or self.data.transport == "local_udp":
            try:
                await self.local_client.async_send_control(
                    ctrl_code=ctrl_code,
                    ctrl_data=ctrl_data,
                    target_ip=target_ip,
                )
                sent_locally = True
            except ValueError as err:
                # Appliance explicitly rejected the operation (busy, pairing, FW update, or door open)
                raise HomeAssistantError(str(err)) from err
            except (TimeoutError, OSError, RuntimeError) as err:
                _LOGGER.debug(
                    "Local UDP CTRLINS (%s=%s) failed (%s); falling back to Cloud",
                    ctrl_code,
                    ctrl_data,
                    err,
                )

        if not sent_locally:
            try:
                await self.cloud_api.async_send_control(
                    self.appliance.dst,
                    self.appliance.src,
                    ctrl_code,
                    ctrl_data,
                )
            except HitachiAuthError as err:
                self.config_entry.async_start_reauth(self.hass)
                raise HomeAssistantError(
                    f"Hitachi authentication expired: {err}"
                ) from err
            except (HitachiCommandError, HitachiConnectionError, HitachiFridgeError) as err:
                raise HomeAssistantError(str(err)) from err

        await asyncio.sleep(POST_CONTROL_DELAY_SECONDS)
        await self.async_request_refresh()

    async def async_set_firmware_auto_update(self, enabled: bool) -> None:
        """Toggle automatic firmware updates (`CMD=FWSETTING`)."""
        try:
            await self.cloud_api.async_set_firmware_auto_update(
                self.appliance.dst, self.appliance.src, enabled
            )
            fw = await self.cloud_api.async_get_firmware_info(
                self.appliance.dst, self.appliance.src
            )
            if fw is not None:
                self._cached_firmware = fw
        except HitachiAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except HitachiFridgeError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()

    async def async_install_firmware(self) -> None:
        """Trigger manual firmware installation (`CMD=FWEXE`)."""
        try:
            await self.cloud_api.async_execute_firmware_update(
                self.appliance.dst, self.appliance.src
            )
            fw = await self.cloud_api.async_get_firmware_info(
                self.appliance.dst, self.appliance.src
            )
            if fw is not None:
                self._cached_firmware = fw
        except HitachiAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except HitachiFridgeError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()

    async def async_set_push_notification(self, push_id: str, enabled: bool) -> None:
        """Enable or mute an app push notification category (`CMD=PUSHREG`)."""
        current_disabled = set(self._cached_disabled_push_ids or set())
        if enabled:
            current_disabled.discard(push_id)
        else:
            current_disabled.add(push_id)

        try:
            await self.cloud_api.async_set_disabled_push_notifications(
                self.appliance.src, current_disabled
            )
            self._cached_disabled_push_ids = current_disabled
        except HitachiAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except HitachiFridgeError as err:
            raise HomeAssistantError(str(err)) from err

        if self.data is not None:
            self.data.disabled_push_ids = set(current_disabled)
            self.async_update_listeners()

    async def async_set_nickname(self, nickname: str) -> None:
        """Update the refrigerator nickname in Hitachi Cloud and HA Device Registry."""
        cleaned = nickname.strip()
        try:
            await self.cloud_api.async_set_device_nickname(
                self.appliance.dst, self.appliance.src, cleaned
            )
        except HitachiAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except HitachiFridgeError as err:
            raise HomeAssistantError(str(err)) from err

        self.appliance.nickname = cleaned
        updated_devices = []
        for item in self.config_entry.data.get(CONF_DEVICES, []):
            if isinstance(item, dict):
                copied = dict(item)
                if copied.get("dst") == self.appliance.dst:
                    copied["nickname"] = cleaned
                updated_devices.append(copied)
        if updated_devices:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_DEVICES: updated_devices},
            )
        dev_reg = dr.async_get(self.hass)
        for dev_entry in dr.async_entries_for_config_entry(
            dev_reg, self.config_entry.entry_id
        ):
            if (
                (DOMAIN, self.appliance.dst) in dev_entry.identifiers
                and not dev_entry.name_by_user
            ):
                dev_reg.async_update_device(dev_entry.id, name=cleaned)
                break
        if self.data is not None:
            self.data.nickname = cleaned
            self.async_update_listeners()

    async def async_rediscover_local_ip(self) -> str:
        """Broadcast `CMD=SEARCH` on UDP `:50000` and refresh telemetry."""
        try:
            ip_addr = await self.local_client.async_discover_ip()
        except (TimeoutError, OSError, RuntimeError) as err:
            raise HomeAssistantError(
                f"Local UDP discovery failed on port 50000: {err}"
            ) from err

        if self._on_ip_discovered is not None and not self.static_ip_override:
            self._on_ip_discovered(self.appliance.dst, ip_addr)
        await self.async_request_refresh()
        return ip_addr

    async def async_force_full_refresh(self) -> None:
        """Force immediate refresh of both `MOVEINF` telemetry and Cloud metadata."""
        self._last_aux_refresh_monotonic = 0.0
        await self.async_request_refresh()
