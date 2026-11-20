"""Constants and per-model capability definitions for the Hitachi Fridge integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "hitachi_fridge"
MANUFACTURER = "Hitachi"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]

# ---------------------------------------------------------------------------
# Cloud & Local UDP Protocol Constants
# ---------------------------------------------------------------------------

ACCOUNT_API_BASE_URL = "https://kadenfan.hitachi.co.jp/my/api/"
APPLIANCE_API_URL = (
    "https://tkg.capsys21.hitachi-gls.co.jp/cgi-bin/ap_outer_ctrl_filter2.cgi"
)
APP_ID = "7"

UDP_PORT = 50000
UDP_BROADCAST_ADDR = "255.255.255.255"
UDP_TIMEOUT_SECONDS = 2.0
POST_CONTROL_DELAY_SECONDS = 0.25

DEFAULT_LOCAL_SCAN_INTERVAL = 5
MIN_LOCAL_SCAN_INTERVAL = 3
MAX_LOCAL_SCAN_INTERVAL = 60

DEFAULT_CLOUD_SCAN_INTERVAL = 60
MIN_CLOUD_SCAN_INTERVAL = 30
MAX_CLOUD_SCAN_INTERVAL = 300

AUX_METADATA_REFRESH_SECONDS = 1800  # 30 minutes for CMD=DELIVERY, FWINFO, HISTORY, PUSHINF
LOGIN_CHECK_REFRESH_SECONDS = 900  # 15 minutes for proactive CMD=LOGINCHK renewal
LOCAL_REDISCOVERY_CLOUD_CYCLES = 3  # Re-probe Local UDP every N cloud fallback cycles

UNAVAILABLE_UINT16 = 0xFFFF

# ---------------------------------------------------------------------------
# Config Entry Data & Option Keys
# ---------------------------------------------------------------------------

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_FRIDGE_IP = "fridge_ip"

CONF_CSPF_ID = "cspf_id"
CONF_CKDN_TOKEN = "ckdn_token"
CONF_CKDN_KEY = "ckdn_key"
CONF_CKDN_IV = "ckdn_iv"
CONF_LOGIN_DATETIME = "login_datetime"
CONF_DEVICES = "devices"

CONF_DST = "dst"
CONF_SRC = "src"
CONF_NICKNAME = "nickname"
CONF_USERNAME = "username"
CONF_LANG = "lang"
CONF_DEVICE_KEY = "device_key"
CONF_DEVICE_IV = "device_iv"

CONF_LOCAL_SCAN_INTERVAL = "local_scan_interval"
CONF_CLOUD_SCAN_INTERVAL = "cloud_scan_interval"
CONF_STATIC_IPS = "static_ips"

# ---------------------------------------------------------------------------
# Control Command Codes (`CTRLINS`)
# ---------------------------------------------------------------------------


class CtrlCode(StrEnum):
    """Appliance control instruction codes (`HR00300Fragment`)."""

    FREEZER_TEMP = "0001"
    REFRIGERATOR_TEMP = "0002"
    ENERGY_SAVER = "0003"
    VACUUM_COMPARTMENT = "0004"
    ICE_MAKER = "0005"
    QUICK_COOLING_OR_SPOT = "0006"
    CONTROL_LOCK = "0007"
    DOOR_ALARM_VOLUME = "0009"
    QUICK_FREEZING_OR_SPEED = "000A"
    SWITCH_ROOM_UPPER_TEMP = "000B"
    SWITCH_ROOM_LOWER_TEMP = "000C"
    VEGETABLE_COMPARTMENT = "000D"


# ---------------------------------------------------------------------------
# Value Enums & Lookup Tables
# ---------------------------------------------------------------------------


class ModelFamily(StrEnum):
    """Hardware UI and protocol family derived from the 8-char `DST` prefix."""

    OVERSEAS_WB = "overseas_wb"  # R-WB640*, R-WB700*, R-WB780* (HCPT / AHTH)
    JP_KWC = "jp_kwc"  # R-KWC570KH/KS (Upper & Lower Switch Rooms)
    JP_KX = "jp_kx"  # R-KX570K (Switch Room predecessor)
    JP_GWC = "jp_gwc"  # R-GWC670TH/TS/YS
    JP_WXC_ZXC = "jp_wxc_zxc"  # R-WXC620/670/740*, R-ZXC740*


class TempControlMode(StrEnum):
    """Granularity of temperature setting reported in byte 12 (`tempControlMode`)."""

    NORMAL = "normal"  # "1" -> 3-step mode
    FINE = "fine"  # "2" -> 9-step (WB) or 11-step (JP) mode


class SelectableZoneMode(StrEnum):
    """4-mode Selectable Zone reported on overseas `R-WB*` models (byte 33, `HR00301Fragment`)."""

    FREEZER = "freezer"  # 1 -> HR00301_21_0 (-18 to -20 C)
    SOFT_FREEZE = "soft_freeze"  # 2 -> HR00301_21_1 (-3 C)
    CHILL_MEAT = "chill_meat"  # 3 -> HR00301_21_2 (1 C)
    REFRIGERATOR = "refrigerator"  # 4 -> HR00301_21_3 (3 C)


SELECTABLE_ZONE_RAW_TO_MODE: dict[int, SelectableZoneMode] = {
    1: SelectableZoneMode.FREEZER,
    2: SelectableZoneMode.SOFT_FREEZE,
    3: SelectableZoneMode.CHILL_MEAT,
    4: SelectableZoneMode.REFRIGERATOR,
}

SELECTABLE_ZONE_TEMP_HINTS: dict[SelectableZoneMode, str] = {
    SelectableZoneMode.FREEZER: "-18 to -20 °C",
    SelectableZoneMode.SOFT_FREEZE: "-3 °C",
    SelectableZoneMode.CHILL_MEAT: "1 °C",
    SelectableZoneMode.REFRIGERATOR: "3 °C",
}


class SwitchRoomMode(StrEnum):
    """2-mode Switch Room setting on Japanese `R-KWC570*` / `R-KX*` models (byte 35)."""

    REFRIGERATOR_CHILLED_VEG = "refrigerator_chilled_veg"  # bit == 0
    FREEZER_SOFT_FREEZE = "freezer_soft_freeze"  # bit == 1


# Overseas WB (`HCPT`) temperature step mappings (Coldest=9 .. Cold=1)
WB_TEMP_NORMAL_OPTIONS: dict[str, int] = {
    "coldest": 9,
    "mid": 5,
    "cold": 1,
}
WB_TEMP_FINE_OPTIONS: dict[str, int] = {
    "step_9_coldest": 9,
    "step_8": 8,
    "step_7": 7,
    "step_6": 6,
    "step_5_mid": 5,
    "step_4": 4,
    "step_3": 3,
    "step_2": 2,
    "step_1_cold": 1,
}

# Japanese (`WXC`/`ZXC`/`GWC`/`KWC`/`KX`) temperature step mappings (11..1)
JP_TEMP_NORMAL_OPTIONS: dict[str, int] = {
    "high": 10,
    "mid": 6,
    "low": 2,
}
JP_TEMP_FINE_OPTIONS: dict[str, int] = {
    "step_11": 11,
    "step_10_high": 10,
    "step_9": 9,
    "step_8": 8,
    "step_7": 7,
    "step_6_mid": 6,
    "step_5": 5,
    "step_4": 4,
    "step_3": 3,
    "step_2_low": 2,
    "step_1": 1,
}

# Vacuum Compartment (`HR00300Fragment`: "02"=+1 C Chilled, "01"=-1 C Sub Zero, "00"=Off)
VACUUM_3MODE_OPTIONS: dict[str, int] = {
    "off": 0,
    "sub_zero": 1,
    "chilled": 2,
}

ICE_MAKER_JP_OPTIONS: dict[str, int] = {
    "off": 0,
    "on": 1,
    "quick_ice_making": 2,
}

# Sound / Door Alarm Volume (`MoveInfo.volume` + `HR00300Fragment`: "01"=Mid, "02"=Max, "00"=Off)
DOOR_ALARM_VOLUME_OPTIONS: dict[str, int] = {
    "off": 0,
    "mid": 1,
    "max": 2,
}

# Notification `infoCode` descriptions (`HR00600RvAdapter` & `HR00601Activity` + `strings.xml`)
INFO_CODE_DESCRIPTIONS: dict[str, str] = {
    "000": "Normal",
    "001": "Ice container cleaning complete",
    "002": "Upper selectable compartment temperature selection complete",
    "003": "Lower selectable compartment temperature selection complete",
    "004": "Ice making complete",
    "005": "Selectable Zone compartment setting changed",
}

PUSH_NOTIFICATION_SWITCH_KEYS: dict[str, str] = {
    "0001": "push_notify_ice_and_operation",
    "0002": "push_notify_door_and_alert",
    "0003": "push_notify_cooling_complete",
    "0004": "push_notify_upper_compartment",
    "0005": "push_notify_lower_compartment",
    "0007": "push_notify_quick_mode",
}

# ---------------------------------------------------------------------------
# Strict Per-Model Capability Matrix (`Constant`, `HR00300Fragment`, `HR00301Fragment`, `HR00800Activity`)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Exact telemetry and control capabilities supported by a refrigerator model."""

    model_name: str
    family: ModelFamily
    temp_scale_steps: int  # 9 for WB, 11 for JP

    # Controls (`HR00300Fragment.setViewItem` & `onWidgetClick`)
    has_refrigerator_temp: bool = True
    has_freezer_temp: bool = True
    vacuum_modes: int = 3  # 3 -> SelectEntity (Off/Chilled/Sub Zero), 2 -> SwitchEntity (On/Off), 0 -> None
    ice_maker_modes: int = 3  # 3 -> SelectEntity (Off/On/Quick), 2 -> SwitchEntity (On/Off)
    has_energy_saver: bool = True
    has_quick_cooling_wb: bool = False  # CTRLC 0006, freezingMode bit 0 (0x01)
    has_quick_freezing_wb: bool = False  # CTRLC 000A, freezingMode bit 1 (0x02), status bit 5 (0x20)
    has_quick_cooling_gwc: bool = False  # CTRLC 000A, freezingMode bit 3 (0x08), status bit 5 (0x20)
    has_spot_cooling: bool = False  # CTRLC 0006, freezingMode bit 0 (0x01)
    has_speed_cooling: bool = False  # CTRLC 000A, freezingMode bit 1 (0x02)
    has_vegetable_compartment: bool = False  # CTRLC 000D, freezingMode bit 2 (0x04)
    has_door_alarm_volume: bool = False  # CTRLC 0009
    has_control_lock: bool = False  # CTRLC 0007
    has_switch_room_temp_controls: bool = False  # CTRLC 000B & 000C

    # Telemetry & Status Indicators (`HR00301Fragment` & `Constant.checkIsDoorTimeChart`)
    has_selectable_zone: bool = False  # 4-mode Selectable Zone (byte 33 on R-WB*)
    has_switch_rooms: bool = False  # Upper & Lower Switch Room modes/status (bytes 35..36)
    has_door_duration_telemetry: bool = False  # Per-door open duration seconds (bytes 37..44)
    has_electric_drawer: bool = False  # Auto door / electric drawer status (byte 18 on R-ZXC*)
    has_jp_move_sign_badges: bool = False  # Additional JP Frost Recycle / Delicious Freezing status badges

    # Cloud Notification Switches (`HR00800Activity.initView`)
    supported_push_ids: tuple[str, ...] = ("0002",)


def _wb_caps(model_name: str) -> ModelCapabilities:
    """Capabilities for Overseas WB / AHTH (`HCPT`) models (`R-WB640*`, `R-WB700*`, `R-WB780*`)."""
    return ModelCapabilities(
        model_name=model_name,
        family=ModelFamily.OVERSEAS_WB,
        temp_scale_steps=9,
        has_refrigerator_temp=True,
        has_freezer_temp=True,
        vacuum_modes=3,
        ice_maker_modes=2,
        has_energy_saver=True,
        has_quick_cooling_wb=True,
        has_quick_freezing_wb=True,
        has_quick_cooling_gwc=False,
        has_spot_cooling=False,
        has_speed_cooling=False,
        has_vegetable_compartment=False,
        has_door_alarm_volume=False,
        has_control_lock=False,
        has_switch_room_temp_controls=False,
        has_selectable_zone=True,
        has_switch_rooms=False,
        has_door_duration_telemetry=False,
        has_electric_drawer=False,
        has_jp_move_sign_badges=False,
        supported_push_ids=("0002", "0007"),
    )


def _kwc_caps(model_name: str) -> ModelCapabilities:
    """Capabilities for Japanese Switch Room models (`R-KWC570KH`, `R-KWC570KS`)."""
    return ModelCapabilities(
        model_name=model_name,
        family=ModelFamily.JP_KWC,
        temp_scale_steps=11,
        has_refrigerator_temp=True,
        has_freezer_temp=False,  # mLL7 is hidden on KWC570; Upper/Lower Switch Rooms replace it
        vacuum_modes=2,
        ice_maker_modes=3,
        has_energy_saver=True,
        has_quick_cooling_wb=False,
        has_quick_freezing_wb=False,
        has_quick_cooling_gwc=False,
        has_spot_cooling=False,
        has_speed_cooling=False,
        has_vegetable_compartment=False,
        has_door_alarm_volume=True,
        has_control_lock=True,
        has_switch_room_temp_controls=False,  # mLL16/mLL17 hidden on KWC570 (`HR00300Fragment.setViewItem`); active on KX570K
        has_selectable_zone=False,
        has_switch_rooms=True,
        has_door_duration_telemetry=False,
        has_electric_drawer=False,
        has_jp_move_sign_badges=True,
        supported_push_ids=("0001", "0002", "0003", "0004", "0005"),
    )


def _gwc_caps(model_name: str) -> ModelCapabilities:
    """Capabilities for Japanese GWC models (`R-GWC670TH`, `R-GWC670TS`, `R-GWC670YS`)."""
    return ModelCapabilities(
        model_name=model_name,
        family=ModelFamily.JP_GWC,
        temp_scale_steps=11,
        has_refrigerator_temp=True,
        has_freezer_temp=True,
        vacuum_modes=2,
        ice_maker_modes=3,
        has_energy_saver=True,
        has_quick_cooling_wb=False,
        has_quick_freezing_wb=False,
        has_quick_cooling_gwc=True,
        has_spot_cooling=False,
        has_speed_cooling=False,
        has_vegetable_compartment=True,
        has_door_alarm_volume=True,
        has_control_lock=True,
        has_switch_room_temp_controls=False,
        has_selectable_zone=False,
        has_switch_rooms=False,
        has_door_duration_telemetry=True,
        has_electric_drawer=False,
        has_jp_move_sign_badges=True,
        supported_push_ids=("0001", "0002", "0003"),
    )


def _wxc_zxc_caps(
    model_name: str,
    *,
    is_zxc: bool = False,
    has_door_duration: bool = False,
) -> ModelCapabilities:
    """Capabilities for Japanese WXC / ZXC flagship models."""
    return ModelCapabilities(
        model_name=model_name,
        family=ModelFamily.JP_WXC_ZXC,
        temp_scale_steps=11,
        has_refrigerator_temp=True,
        has_freezer_temp=True,
        vacuum_modes=3,
        ice_maker_modes=3,
        has_energy_saver=True,
        has_quick_cooling_wb=False,
        has_quick_freezing_wb=False,
        has_quick_cooling_gwc=False,
        has_spot_cooling=True,
        has_speed_cooling=True,
        has_vegetable_compartment=True,
        has_door_alarm_volume=True,
        has_control_lock=True,
        has_switch_room_temp_controls=False,
        has_selectable_zone=False,
        has_switch_rooms=False,
        has_door_duration_telemetry=has_door_duration,
        has_electric_drawer=is_zxc,
        has_jp_move_sign_badges=True,
        supported_push_ids=("0001", "0002", "0003"),
    )


MODEL_CAPABILITIES_BY_PREFIX: dict[str, ModelCapabilities] = {
    # Overseas WB / AHTH (`HCPT`)
    "0500CE4B": _wb_caps("R-WB640VFX"),
    "01002C82": _wb_caps("R-WB640VH0X"),
    "0500CE4E": _wb_caps("R-WB640V0MSX"),
    "0500D15E": _wb_caps("R-WB700VFX"),
    "0500D2D5": _wb_caps("R-WB780VMS3X"),
    # Japanese Switch Room (`KWC570` & `KX`)
    "0100237E": _kwc_caps("R-KWC570KH"),
    "0100237F": _kwc_caps("R-KWC570KS"),
    "01002029": ModelCapabilities(
        model_name="R-KX570K",
        family=ModelFamily.JP_KX,
        temp_scale_steps=11,
        has_refrigerator_temp=True,
        has_freezer_temp=False,
        vacuum_modes=0,  # KX series has no Vacuum Compartment
        ice_maker_modes=3,
        has_energy_saver=True,
        has_door_alarm_volume=True,
        has_control_lock=True,
        has_switch_room_temp_controls=True,
        has_switch_rooms=True,
        has_jp_move_sign_badges=True,
        supported_push_ids=("0001", "0002", "0003", "0004", "0005"),
    ),
    # Japanese GWC
    "01104494": _gwc_caps("R-GWC670TH"),
    "01104487": _gwc_caps("R-GWC670TS"),
    "211055A8": _gwc_caps("R-GWC670YS"),
    # Japanese WXC
    "01002295": _wxc_zxc_caps("R-WXC620KS"),
    "0100229A": _wxc_zxc_caps("R-WXC670KH"),
    "01002294": _wxc_zxc_caps("R-WXC670KS"),
    "01003BF5": _wxc_zxc_caps("R-WXC670RH"),
    "01002299": _wxc_zxc_caps("R-WXC740KH"),
    "01002293": _wxc_zxc_caps("R-WXC740KS"),
    "01003BF3": _wxc_zxc_caps("R-WXC740RH"),
    "01104B07": _wxc_zxc_caps("R-WXC740WH", has_door_duration=True),
    "01104AF9": _wxc_zxc_caps("R-WXC740WS", has_door_duration=True),
    # Japanese ZXC (with Electric Drawer)
    "01002298": _wxc_zxc_caps("R-ZXC740KH", is_zxc=True),
    "01002291": _wxc_zxc_caps("R-ZXC740KJ", is_zxc=True),
    "01002292": _wxc_zxc_caps("R-ZXC740KS", is_zxc=True),
    "01002296": _wxc_zxc_caps("R-ZXC740KT", is_zxc=True),
    "01003BF1": _wxc_zxc_caps("R-ZXC740RH", is_zxc=True),
    "01003C0F": _wxc_zxc_caps("R-ZXC740RT", is_zxc=True),
    "01104B05": _wxc_zxc_caps("R-ZXC740WH", is_zxc=True, has_door_duration=True),
    "01104AF7": _wxc_zxc_caps("R-ZXC740WS", is_zxc=True, has_door_duration=True),
}


def get_model_capabilities(dst: str) -> ModelCapabilities:
    """Resolve `ModelCapabilities` from an appliance's 8-character `DST` prefix.

    Unknown future prefixes default to the Japanese WXC/ZXC layout, matching the
    `else` fallthrough in `HR00300Fragment.setViewItem()`.
    """
    prefix = (dst or "")[:8].upper()
    if prefix in MODEL_CAPABILITIES_BY_PREFIX:
        return MODEL_CAPABILITIES_BY_PREFIX[prefix]
    return _wxc_zxc_caps(f"Hitachi Smart Fridge ({prefix or 'Unknown'})")
