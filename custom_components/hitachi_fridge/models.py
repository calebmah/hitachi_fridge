"""Data models and 45-byte `MOVEINF` telemetry decoder for Hitachi Fridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .const import (
    CONF_CKDN_IV,
    CONF_CKDN_KEY,
    CONF_CKDN_TOKEN,
    CONF_CSPF_ID,
    CONF_DEVICE_IV,
    CONF_DEVICE_KEY,
    CONF_DST,
    CONF_FRIDGE_IP,
    CONF_LANG,
    CONF_LOGIN_DATETIME,
    CONF_NICKNAME,
    CONF_SRC,
    CONF_USERNAME,
    JP_TEMP_FINE_OPTIONS,
    JP_TEMP_NORMAL_OPTIONS,
    SELECTABLE_ZONE_RAW_TO_MODE,
    UNAVAILABLE_UINT16,
    WB_TEMP_FINE_OPTIONS,
    WB_TEMP_NORMAL_OPTIONS,
    ModelCapabilities,
    ModelFamily,
    SelectableZoneMode,
    SwitchRoomMode,
    TempControlMode,
    get_model_capabilities,
)


@dataclass(slots=True)
class CloudSessionData:
    """Authenticated Hitachi Cloud session credentials (`ResGetHid`)."""

    cspf_id: str
    ckdn_token: str
    ckdn_key_hex: str
    ckdn_iv_hex: str
    login_datetime: str = ""
    udp_keys_by_dst: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def ckdn_key(self) -> bytes:
        """Return 32-byte AES-256 session key."""
        return bytes.fromhex(self.ckdn_key_hex)

    @property
    def ckdn_iv(self) -> bytes:
        """Return 16-byte AES-256 session IV."""
        return bytes.fromhex(self.ckdn_iv_hex)

    def to_config_dict(self) -> dict[str, Any]:
        """Serialize session fields for `ConfigEntry.data`."""
        return {
            CONF_CSPF_ID: self.cspf_id,
            CONF_CKDN_TOKEN: self.ckdn_token,
            CONF_CKDN_KEY: self.ckdn_key_hex,
            CONF_CKDN_IV: self.ckdn_iv_hex,
            CONF_LOGIN_DATETIME: self.login_datetime,
        }

    @classmethod
    def from_config_dict(cls, data: dict[str, Any]) -> CloudSessionData | None:
        """Restore `CloudSessionData` from `ConfigEntry.data` if present."""
        cspf_id = data.get(CONF_CSPF_ID)
        ckdn_token = data.get(CONF_CKDN_TOKEN)
        ckdn_key = data.get(CONF_CKDN_KEY)
        ckdn_iv = data.get(CONF_CKDN_IV)
        if not (cspf_id and ckdn_token and ckdn_key and ckdn_iv):
            return None
        return cls(
            cspf_id=str(cspf_id),
            ckdn_token=str(ckdn_token),
            ckdn_key_hex=str(ckdn_key),
            ckdn_iv_hex=str(ckdn_iv),
            login_datetime=str(data.get(CONF_LOGIN_DATETIME) or ""),
        )


@dataclass(slots=True)
class ApplianceDevice:
    """Paired Hitachi refrigerator metadata and Local LAN UDP credentials."""

    dst: str
    src: str
    nickname: str = "Hitachi Fridge"
    username: str = ""
    lang: str = "en"
    device_key_hex: str = ""
    device_iv_hex: str = ""
    fridge_ip: str | None = None

    @property
    def device_key(self) -> bytes | None:
        """Return 32-byte per-device Local UDP AES key if provisioned."""
        return bytes.fromhex(self.device_key_hex) if self.device_key_hex else None

    @property
    def device_iv(self) -> bytes | None:
        """Return 16-byte per-device Local UDP IV if provisioned."""
        return bytes.fromhex(self.device_iv_hex) if self.device_iv_hex else None

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return model-specific telemetry and control capabilities."""
        return get_model_capabilities(self.dst)

    def to_config_dict(self) -> dict[str, Any]:
        """Serialize appliance record for `ConfigEntry.data`."""
        return {
            CONF_DST: self.dst,
            CONF_SRC: self.src,
            CONF_NICKNAME: self.nickname,
            CONF_USERNAME: self.username,
            CONF_LANG: self.lang,
            CONF_DEVICE_KEY: self.device_key_hex,
            CONF_DEVICE_IV: self.device_iv_hex,
            CONF_FRIDGE_IP: self.fridge_ip,
        }

    @classmethod
    def from_config_dict(cls, data: dict[str, Any]) -> ApplianceDevice:
        """Deserialize appliance record from `ConfigEntry.data`."""
        return cls(
            dst=str(data[CONF_DST]),
            src=str(data[CONF_SRC]),
            nickname=str(data.get(CONF_NICKNAME) or "Hitachi Fridge"),
            username=str(data.get(CONF_USERNAME) or ""),
            lang=str(data.get(CONF_LANG) or "en"),
            device_key_hex=str(data.get(CONF_DEVICE_KEY) or ""),
            device_iv_hex=str(data.get(CONF_DEVICE_IV) or ""),
            fridge_ip=data.get(CONF_FRIDGE_IP) or None,
        )


@dataclass(slots=True)
class DailyDoorStat:
    """Completed 24-hour door-open statistics from `CMD=DELIVERY` (`HR00301_M11`/`M12`)."""

    stat_date: date
    door_opens: int | None
    refrigerator_open_seconds: int | None  # doorFOpenTime* (`HR00301_M11`: Refrigerator compartment door)
    drawer_open_seconds: int | None  # doorDOpenTime* (`HR00301_M12`: Drawer door)


@dataclass(slots=True)
class AlarmHistoryEntry:
    """Historical notification or error entry from `CMD=HISTORY` (`DataHistory`)."""

    timestamp: str
    info_code: str
    error_code: str


@dataclass(slots=True)
class FirmwareStatus:
    """Appliance firmware status from `CMD=FWINFO` (`ResFwInfo`)."""

    version: str
    auto_update_enabled: bool
    update_available: bool
    update_in_progress: bool
    raw_status: str
    raw_mode: str


@dataclass(slots=True)
class FridgeTelemetry:
    """Complete decoded 45-byte (`90`-hex-char) `MOVEINF` refrigerator status."""

    raw_hex: str
    model_family: ModelFamily
    appliance_timestamp: datetime | None

    # Temperature settings & granularity
    temp_control_mode: TempControlMode
    freezer_temp_raw: int
    refrigerator_temp_raw: int

    # Compartment modes & switches
    energy_saving: bool
    vacuum_mode_raw: int
    ice_maker_raw: int
    quick_cooling_wb: bool
    quick_freezing_wb: bool
    quick_cooling_gwc: bool
    spot_cooling: bool
    speed_cooling: bool
    vegetable_compartment: bool
    control_lock: bool
    electric_drawer: bool
    door_alarm_volume_raw: int

    # Door open counts & cumulative open durations (seconds)
    # `F` = Refrigerator compartment French/hinged door (`HR00301_M11`)
    # `D` = Drawer door (`HR00301_M12`)
    door_opens_today: int | None
    door_opens_yesterday: int | None
    door_f_open_seconds_today: int | None
    door_d_open_seconds_today: int | None
    door_f_open_seconds_yesterday: int | None
    door_d_open_seconds_yesterday: int | None

    # Selectable Zone (`R-WB*`) & Upper/Lower Switch Rooms (`R-KWC570*` / `R-KX*`)
    selectable_zone_mode: SelectableZoneMode | None
    selectable_zone_switching: bool  # switchRoomUpperStatus bit 0 on `R-WB*` (`M0078`)
    switch_room_upper_mode: SwitchRoomMode | None
    switch_room_lower_mode: SwitchRoomMode | None
    switch_room_upper_temp_raw: int
    switch_room_lower_temp_raw: int
    switch_room_upper_switching: bool  # switchRoomUpperStatus bit 0 (`M0067`)
    switch_room_lower_switching: bool  # switchRoomLowerStatus bit 1 (`M0068`)

    # Operating status badges & diagnostics (`fragment_hr00301.xml` + `HR00301Fragment` + `HR00300Fragment.showMsg`)
    status_flags: int
    move_sign_flags: int
    eco_operation_active: bool  # moveSign bit 0 (0x01, mLL2 -> M0060: In power save mode)
    water_tank_empty: bool  # moveSign bit 1 (0x02, mLL4 -> HR00301_5 / M0061: Water supply low)
    door_open: bool  # moveSign bit 2 (0x04, mLL3 -> HR00301_3 / M0066 / HR00300_45: Door is open)
    ice_maker_cleaning: bool  # status bit 0 (0x01, mLL5 -> HR00301_7 / M0062 / HR00300_46: Cleaning ice maker)
    ice_making_active: bool  # status bit 1 (0x02, mLL6 -> HR00301_9 / M0063 / HR00300_47: Ice making)
    rapid_ice_status_active: bool  # status bit 2 (0x04, mLL7 -> HR00301_11 / M0064: Making ice quickly)
    quick_or_spot_cooling_in_progress: bool  # status bit 3 (0x08, mLL8 -> WB Quick Cooling M0081 / JP Spot Cooling M0065)
    under_maintenance: bool  # status bit 4 (0x10, HR00300_44: Under maintenance)
    quick_mode_in_progress: bool  # status bit 5 (0x20, WB mLL11 Quick Freezing M0080 / GWC mLL12 Quick Cooling HR00301_24)
    integral_drive_time: int
    integral_drive_time_hex: str
    info_code: str
    error_code: str

    @classmethod
    def from_moveinf_hex(
        cls,
        hex_str: str,
        dst: str,
        tz: tzinfo | None = None,
    ) -> FridgeTelemetry:
        """Decode a 74- or 90-character hexadecimal `MOVEINF` payload (`DataMoveInf.init`).

        Models without per-door duration telemetry (`checkIsDoorTimeChart() == false`,
        such as `R-WB*`) return 37 bytes (`74` hex chars); models with door duration
        telemetry append bytes `37..44` for 45 bytes (`90` hex chars).
        """
        clean = hex_str.strip()
        if len(clean) < 74:
            raise ValueError(
                f"Expected >=74-hex-char MOVEINF payload, got {len(clean)} chars"
            )

        caps = get_model_capabilities(dst)
        family = caps.family

        year = int(clean[0:4], 16)
        month = int(clean[4:6], 16)
        day = int(clean[6:8], 16)
        hour = int(clean[8:10], 16)
        minute = int(clean[10:12], 16)
        second = int(clean[12:14], 16)
        local_tz = tz or datetime.now().astimezone().tzinfo
        try:
            appliance_ts = datetime(
                year, month, day, hour, minute, second, tzinfo=local_tz
            )
        except ValueError:
            appliance_ts = None

        status_flags = int(clean[16:18], 16)
        move_sign_flags = int(clean[18:20], 16)
        freeze_raw = int(clean[20:22], 16)
        ref_raw = int(clean[22:24], 16)
        temp_mode_raw = int(clean[24:26], 16)
        temp_mode = (
            TempControlMode.FINE if temp_mode_raw == 2 else TempControlMode.NORMAL
        )

        power_saving = int(clean[26:28], 16) == 1
        vacuum_raw = int(clean[28:30], 16)
        ice_raw = int(clean[30:32], 16)
        freezing_bits = int(clean[32:34], 16)
        control_lock = int(clean[34:36], 16) == 1
        electric_drawer = int(clean[36:38], 16) == 1
        volume_raw = int(clean[38:40], 16)

        opens_today_raw = int(clean[40:44], 16)
        opens_yest_raw = int(clean[44:48], 16)

        drive_time_hex = clean[48:54].upper()
        drive_time_int = int(drive_time_hex, 16)
        info_code = (
            bytes.fromhex(clean[54:60])
            .decode("ascii", errors="replace")
            .strip("\x00")
            or "000"
        )
        error_code = (
            bytes.fromhex(clean[60:66])
            .decode("ascii", errors="replace")
            .strip("\x00")
            or "000"
        )

        sr_upper_temp = int(clean[66:68], 16)
        sr_lower_temp = int(clean[68:70], 16)
        sr_modes_bits = int(clean[70:72], 16)
        sr_status_bits = int(clean[72:74], 16)

        if len(clean) >= 90:
            f_today = int(clean[74:78], 16)
            d_today = int(clean[78:82], 16)
            f_yest = int(clean[82:86], 16)
            d_yest = int(clean[86:90], 16)
        else:
            f_today = UNAVAILABLE_UINT16
            d_today = UNAVAILABLE_UINT16
            f_yest = UNAVAILABLE_UINT16
            d_yest = UNAVAILABLE_UINT16

        selectable_zone: SelectableZoneMode | None = None
        sr_upper_mode: SwitchRoomMode | None = None
        sr_lower_mode: SwitchRoomMode | None = None

        if caps.has_selectable_zone:
            selectable_zone = SELECTABLE_ZONE_RAW_TO_MODE.get(sr_upper_temp)

        if caps.has_switch_rooms:
            sr_upper_mode = (
                SwitchRoomMode.FREEZER_SOFT_FREEZE
                if (sr_modes_bits & 0x01)
                else SwitchRoomMode.REFRIGERATOR_CHILLED_VEG
            )
            sr_lower_mode = (
                SwitchRoomMode.FREEZER_SOFT_FREEZE
                if (sr_modes_bits & 0x02)
                else SwitchRoomMode.REFRIGERATOR_CHILLED_VEG
            )

        upper_switching = bool(sr_status_bits & 0x01)

        return cls(
            raw_hex=clean.upper(),
            model_family=family,
            appliance_timestamp=appliance_ts,
            temp_control_mode=temp_mode,
            freezer_temp_raw=freeze_raw,
            refrigerator_temp_raw=ref_raw,
            energy_saving=power_saving,
            vacuum_mode_raw=vacuum_raw,
            ice_maker_raw=ice_raw,
            quick_cooling_wb=bool(freezing_bits & 0x01) if caps.has_quick_cooling_wb else False,
            quick_freezing_wb=bool(freezing_bits & 0x02) if caps.has_quick_freezing_wb else False,
            quick_cooling_gwc=bool(freezing_bits & 0x08) if caps.has_quick_cooling_gwc else False,
            spot_cooling=bool(freezing_bits & 0x01) if caps.has_spot_cooling else False,
            speed_cooling=bool(freezing_bits & 0x02) if caps.has_speed_cooling else False,
            vegetable_compartment=bool(freezing_bits & 0x04),
            control_lock=control_lock,
            electric_drawer=electric_drawer,
            door_alarm_volume_raw=volume_raw,
            door_opens_today=(
                None if opens_today_raw == UNAVAILABLE_UINT16 else opens_today_raw
            ),
            door_opens_yesterday=(
                None if opens_yest_raw == UNAVAILABLE_UINT16 else opens_yest_raw
            ),
            door_f_open_seconds_today=(
                None if f_today == UNAVAILABLE_UINT16 else f_today
            ),
            door_d_open_seconds_today=(
                None if d_today == UNAVAILABLE_UINT16 else d_today
            ),
            door_f_open_seconds_yesterday=(
                None if f_yest == UNAVAILABLE_UINT16 else f_yest
            ),
            door_d_open_seconds_yesterday=(
                None if d_yest == UNAVAILABLE_UINT16 else d_yest
            ),
            selectable_zone_mode=selectable_zone,
            selectable_zone_switching=upper_switching if caps.has_selectable_zone else False,
            switch_room_upper_mode=sr_upper_mode,
            switch_room_lower_mode=sr_lower_mode,
            switch_room_upper_temp_raw=sr_upper_temp,
            switch_room_lower_temp_raw=sr_lower_temp,
            switch_room_upper_switching=upper_switching if caps.has_switch_rooms else False,
            switch_room_lower_switching=(
                bool(sr_status_bits & 0x02) if caps.has_switch_rooms else False
            ),
            status_flags=status_flags,
            move_sign_flags=move_sign_flags,
            eco_operation_active=bool(move_sign_flags & 0x01),
            water_tank_empty=bool(move_sign_flags & 0x02),
            door_open=bool(move_sign_flags & 0x04),
            ice_maker_cleaning=bool(status_flags & 0x01),
            ice_making_active=bool(status_flags & 0x02),
            rapid_ice_status_active=bool(status_flags & 0x04),
            quick_or_spot_cooling_in_progress=bool(status_flags & 0x08),
            under_maintenance=bool(status_flags & 0x10),
            quick_mode_in_progress=bool(status_flags & 0x20),
            integral_drive_time=drive_time_int,
            integral_drive_time_hex=drive_time_hex,
            info_code=info_code,
            error_code=error_code,
        )


@dataclass(slots=True)
class FridgeCoordinatorSnapshot:
    """Aggregated state snapshot published by `HitachiFridgeCoordinator`."""

    telemetry: FridgeTelemetry
    transport: str  # "local_udp" or "cloud_http"
    fridge_ip: str | None
    nickname: str
    door_history: dict[str, DailyDoorStat] = field(default_factory=dict)
    firmware: FirmwareStatus | None = None
    alarm_history: list[AlarmHistoryEntry] = field(default_factory=list)
    disabled_push_ids: set[str] | None = None


def get_temp_option_map(
    family: ModelFamily,
    mode: TempControlMode,
    current_raw: int | None = None,
) -> dict[str, int]:
    """Return temperature option-key -> raw-step mapping for a model & mode.

    If the refrigerator reports `NORMAL` mode (`"1"`) while holding an intermediate
    step value, falls back to the `FINE` table so `current_option` is always valid.
    """
    if family == ModelFamily.OVERSEAS_WB:
        normal_map = WB_TEMP_NORMAL_OPTIONS
        fine_map = WB_TEMP_FINE_OPTIONS
    else:
        normal_map = JP_TEMP_NORMAL_OPTIONS
        fine_map = JP_TEMP_FINE_OPTIONS

    if mode == TempControlMode.FINE:
        return fine_map
    if current_raw is not None and current_raw not in normal_map.values():
        if current_raw in fine_map.values():
            return fine_map
    return normal_map


def extract_cloud_moveinf_hex(data_field: str) -> str:
    """Extract the 74- or 90-hex-char `MOVEINF` payload from Cloud `ResMoveInf.DATA`.

    In `HR00300Fragment.java` and `LocalService.java`, Cloud `ResMoveInf.DATA` is
    comma-separated with the hex payload at index `3` (`split(",")[3]`),
    whereas Local UDP `MOVEINF` puts it at index `1`.
    """
    raw = (data_field or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) >= 4 and len(parts[3]) >= 74:
        return parts[3]
    for token in reversed(parts):
        if len(token) >= 74:
            return token
    return parts[-1]


def parse_door_history_csv(data_csv: str) -> dict[str, DailyDoorStat]:
    """Parse comma-separated 74- or 90-hex-char midnight snapshots (`CMD=DELIVERY`).

    Each snapshot stamped just after midnight on date `D` records completed
    24-hour totals for `D - 1 day` (`GraphData.addObject`).
    """
    if not data_csv:
        return {}
    by_date: dict[str, DailyDoorStat] = {}
    for item in data_csv.split(","):
        snap = item.strip()
        if len(snap) < 74:
            continue
        try:
            year = int(snap[0:4], 16)
            month = int(snap[4:6], 16)
            day = int(snap[6:8], 16)
            stat_day = date(year, month, day) - timedelta(days=1)
            opens_raw = int(snap[44:48], 16)
            f_sec_raw = int(snap[82:86], 16) if len(snap) >= 90 else UNAVAILABLE_UINT16
            d_sec_raw = int(snap[86:90], 16) if len(snap) >= 90 else UNAVAILABLE_UINT16
        except ValueError:
            continue
        by_date[stat_day.isoformat()] = DailyDoorStat(
            stat_date=stat_day,
            door_opens=None if opens_raw == UNAVAILABLE_UINT16 else opens_raw,
            refrigerator_open_seconds=(
                None if f_sec_raw == UNAVAILABLE_UINT16 else f_sec_raw
            ),
            drawer_open_seconds=(
                None if d_sec_raw == UNAVAILABLE_UINT16 else d_sec_raw
            ),
        )
    return dict(sorted(by_date.items()))


def parse_alarm_history(data_str: str) -> list[AlarmHistoryEntry]:
    """Parse alarm/notification history records from `CMD=HISTORY` (`DataHistory.addObject`)."""
    if not data_str:
        return []
    entries: list[AlarmHistoryEntry] = []
    for raw_token in data_str.replace("|", ",").split(","):
        snap = raw_token.strip()
        if len(snap) < 66:
            continue
        try:
            year = int(snap[0:4], 16)
            month = int(snap[4:6], 16)
            day = int(snap[6:8], 16)
            hour = int(snap[8:10], 16)
            minute = int(snap[10:12], 16)
            info_code = (
                bytes.fromhex(snap[54:60])
                .decode("ascii", errors="replace")
                .strip("\x00")
            )
            error_code = (
                bytes.fromhex(snap[60:66])
                .decode("ascii", errors="replace")
                .strip("\x00")
            )
        except ValueError:
            continue
        if info_code == "000" and error_code == "000":
            continue
        entries.append(
            AlarmHistoryEntry(
                timestamp=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
                info_code=info_code,
                error_code=error_code,
            )
        )
    return entries[:20]
