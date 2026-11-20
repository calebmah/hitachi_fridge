"""Select entities for Hitachi Fridge compartment temperatures and multi-mode controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HitachiFridgeConfigEntry
from .const import (
    DOOR_ALARM_VOLUME_OPTIONS,
    ICE_MAKER_JP_OPTIONS,
    JP_TEMP_FINE_OPTIONS,
    JP_TEMP_NORMAL_OPTIONS,
    VACUUM_3MODE_OPTIONS,
    WB_TEMP_FINE_OPTIONS,
    WB_TEMP_NORMAL_OPTIONS,
    CtrlCode,
    ModelCapabilities,
    ModelFamily,
    TempControlMode,
)
from .coordinator import HitachiFridgeCoordinator
from .entity import HitachiFridgeEntity
from .models import FridgeTelemetry, get_temp_option_map


@dataclass(frozen=True, kw_only=True)
class HitachiTempSelectDescription(SelectEntityDescription):
    """Describe a dynamic Normal/Fine temperature step selector."""

    ctrl_code: CtrlCode
    supported_fn: Callable[[ModelCapabilities], bool]
    raw_value_fn: Callable[[FridgeTelemetry], int]


@dataclass(frozen=True, kw_only=True)
class HitachiStaticSelectDescription(SelectEntityDescription):
    """Describe a fixed multi-option mode selector (`CTRLINS`)."""

    ctrl_code: CtrlCode
    option_map: dict[str, int]
    supported_fn: Callable[[ModelCapabilities], bool]
    raw_value_fn: Callable[[FridgeTelemetry], int]


TEMP_SELECT_DESCRIPTIONS: tuple[HitachiTempSelectDescription, ...] = (
    HitachiTempSelectDescription(
        key="refrigerator_temperature",
        translation_key="refrigerator_temperature",
        icon="mdi:thermometer",
        ctrl_code=CtrlCode.REFRIGERATOR_TEMP,
        supported_fn=lambda caps: caps.has_refrigerator_temp,
        raw_value_fn=lambda tel: tel.refrigerator_temp_raw,
    ),
    HitachiTempSelectDescription(
        key="freezer_temperature",
        translation_key="freezer_temperature",
        icon="mdi:snowflake-thermometer",
        ctrl_code=CtrlCode.FREEZER_TEMP,
        supported_fn=lambda caps: caps.has_freezer_temp,
        raw_value_fn=lambda tel: tel.freezer_temp_raw,
    ),
    HitachiTempSelectDescription(
        key="upper_switch_room_temperature",
        translation_key="upper_switch_room_temperature",
        icon="mdi:archive-arrow-up-outline",
        ctrl_code=CtrlCode.SWITCH_ROOM_UPPER_TEMP,
        supported_fn=lambda caps: caps.has_switch_room_temp_controls,
        raw_value_fn=lambda tel: tel.switch_room_upper_temp_raw,
    ),
    HitachiTempSelectDescription(
        key="lower_switch_room_temperature",
        translation_key="lower_switch_room_temperature",
        icon="mdi:archive-arrow-down-outline",
        ctrl_code=CtrlCode.SWITCH_ROOM_LOWER_TEMP,
        supported_fn=lambda caps: caps.has_switch_room_temp_controls,
        raw_value_fn=lambda tel: tel.switch_room_lower_temp_raw,
    ),
)

STATIC_SELECT_DESCRIPTIONS: tuple[HitachiStaticSelectDescription, ...] = (
    HitachiStaticSelectDescription(
        key="vacuum_compartment",
        translation_key="vacuum_compartment",
        icon="mdi:air-purifier",
        ctrl_code=CtrlCode.VACUUM_COMPARTMENT,
        option_map=VACUUM_3MODE_OPTIONS,
        supported_fn=lambda caps: caps.vacuum_modes == 3,
        raw_value_fn=lambda tel: tel.vacuum_mode_raw,
    ),
    HitachiStaticSelectDescription(
        key="ice_maker_mode",
        translation_key="ice_maker_mode",
        icon="mdi:cube-outline",
        ctrl_code=CtrlCode.ICE_MAKER,
        option_map=ICE_MAKER_JP_OPTIONS,
        supported_fn=lambda caps: caps.ice_maker_modes == 3,
        raw_value_fn=lambda tel: tel.ice_maker_raw,
    ),
    HitachiStaticSelectDescription(
        key="door_alarm_volume",
        translation_key="door_alarm_volume",
        icon="mdi:volume-high",
        entity_category=EntityCategory.CONFIG,
        ctrl_code=CtrlCode.DOOR_ALARM_VOLUME,
        option_map=DOOR_ALARM_VOLUME_OPTIONS,
        supported_fn=lambda caps: caps.has_door_alarm_volume,
        raw_value_fn=lambda tel: tel.door_alarm_volume_raw,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiFridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hitachi Fridge select entities supported by each paired model."""
    entities: list[SelectEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        caps = coord.capabilities
        for temp_desc in TEMP_SELECT_DESCRIPTIONS:
            if temp_desc.supported_fn(caps):
                entities.append(HitachiTemperatureSelectEntity(coord, temp_desc))
        for static_desc in STATIC_SELECT_DESCRIPTIONS:
            if static_desc.supported_fn(caps):
                entities.append(HitachiStaticSelectEntity(coord, static_desc))
    async_add_entities(entities)


class HitachiTemperatureSelectEntity(HitachiFridgeEntity, SelectEntity):
    """Select entity dynamically adapting to Normal (3-step) vs Fine (9/11-step) mode."""

    entity_description: HitachiTempSelectDescription

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        description: HitachiTempSelectDescription,
    ) -> None:
        """Initialize the temperature select entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _active_option_map(self) -> dict[str, int]:
        family = self.coordinator.capabilities.family
        if self.coordinator.data is None:
            return get_temp_option_map(family, TempControlMode.NORMAL)
        tel = self.coordinator.data.telemetry
        raw = self.entity_description.raw_value_fn(tel)
        return get_temp_option_map(family, tel.temp_control_mode, current_raw=raw)

    @property
    def options(self) -> list[str]:
        """Return valid temperature options for the active adjustment granularity."""
        return list(self._active_option_map().keys())

    @property
    def current_option(self) -> str | None:
        """Return the currently selected temperature step."""
        if self.coordinator.data is None:
            return None
        raw = self.entity_description.raw_value_fn(self.coordinator.data.telemetry)
        rev = {step: opt for opt, step in self._active_option_map().items()}
        return rev.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Send `CTRLINS` temperature command for the chosen option."""
        family = self.coordinator.capabilities.family
        all_valid = (
            {**WB_TEMP_NORMAL_OPTIONS, **WB_TEMP_FINE_OPTIONS}
            if family == ModelFamily.OVERSEAS_WB
            else {**JP_TEMP_NORMAL_OPTIONS, **JP_TEMP_FINE_OPTIONS}
        )
        if option not in all_valid:
            raise HomeAssistantError(f"Unsupported temperature option: {option}")
        await self.coordinator.async_send_control(
            self.entity_description.ctrl_code,
            all_valid[option],
        )


class HitachiStaticSelectEntity(HitachiFridgeEntity, SelectEntity):
    """Select entity for multi-mode compartments (Vacuum, JP Ice Maker, Alarm Volume)."""

    entity_description: HitachiStaticSelectDescription

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        description: HitachiStaticSelectDescription,
    ) -> None:
        """Initialize the static select entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.option_map.keys())
        self._rev_map = {val: key for key, val in description.option_map.items()}

    @property
    def current_option(self) -> str | None:
        """Return the active mode option."""
        if self.coordinator.data is None:
            return None
        raw = self.entity_description.raw_value_fn(self.coordinator.data.telemetry)
        return self._rev_map.get(raw)

    async def async_select_option(self, option: str) -> None:
        """Send `CTRLINS` mode command."""
        if option not in self.entity_description.option_map:
            raise HomeAssistantError(f"Unsupported option: {option}")
        await self.coordinator.async_send_control(
            self.entity_description.ctrl_code,
            self.entity_description.option_map[option],
        )
