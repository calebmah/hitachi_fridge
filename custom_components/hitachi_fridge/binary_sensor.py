"""Binary sensor entities for Hitachi Fridge status indicators and alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HitachiFridgeConfigEntry
from .const import INFO_CODE_DESCRIPTIONS, ModelCapabilities, ModelFamily
from .coordinator import HitachiFridgeCoordinator
from .entity import HitachiFridgeEntity
from .models import FridgeCoordinatorSnapshot


@dataclass(frozen=True, kw_only=True)
class HitachiFridgeBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Hitachi Fridge binary sensor entity."""

    supported_fn: Callable[[ModelCapabilities], bool] = lambda _: True
    is_on_fn: Callable[[FridgeCoordinatorSnapshot], bool | None]
    attrs_fn: Callable[[FridgeCoordinatorSnapshot], dict[str, Any]] | None = None


BINARY_SENSOR_DESCRIPTIONS: tuple[HitachiFridgeBinarySensorDescription, ...] = (
    HitachiFridgeBinarySensorDescription(
        key="door_open",
        translation_key="door_open",
        device_class=BinarySensorDeviceClass.DOOR,
        is_on_fn=lambda snap: snap.telemetry.door_open,
    ),
    HitachiFridgeBinarySensorDescription(
        key="water_tank_empty",
        translation_key="water_tank_empty",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-alert-outline",
        is_on_fn=lambda snap: snap.telemetry.water_tank_empty,
    ),
    HitachiFridgeBinarySensorDescription(
        key="alert_active",
        translation_key="alert_active",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda snap: (
            snap.telemetry.error_code != "000" or snap.telemetry.info_code != "000"
        ),
        attrs_fn=lambda snap: {
            "error_code": snap.telemetry.error_code,
            "info_code": snap.telemetry.info_code,
            "info_description": INFO_CODE_DESCRIPTIONS.get(
                snap.telemetry.info_code, f"Notification {snap.telemetry.info_code}"
            ),
        },
    ),
    HitachiFridgeBinarySensorDescription(
        key="ice_making_active",
        translation_key="ice_making_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:cube-outline",
        is_on_fn=lambda snap: snap.telemetry.ice_making_active,
    ),
    HitachiFridgeBinarySensorDescription(
        key="ice_maker_cleaning",
        translation_key="ice_maker_cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:spray-bottle",
        is_on_fn=lambda snap: snap.telemetry.ice_maker_cleaning,
    ),
    HitachiFridgeBinarySensorDescription(
        key="rapid_ice_status_active",
        translation_key="rapid_ice_status_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:ice-pop",
        supported_fn=lambda caps: caps.ice_maker_modes == 3,
        is_on_fn=lambda snap: snap.telemetry.rapid_ice_status_active,
    ),
    HitachiFridgeBinarySensorDescription(
        key="quick_cooling_active",
        translation_key="quick_cooling_active",
        device_class=BinarySensorDeviceClass.COLD,
        icon="mdi:snowflake",
        supported_fn=lambda caps: caps.has_quick_cooling_wb or caps.has_quick_cooling_gwc,
        is_on_fn=lambda snap: (
            snap.telemetry.quick_mode_in_progress
            if snap.telemetry.model_family == ModelFamily.JP_GWC
            else snap.telemetry.quick_or_spot_cooling_in_progress
        ),
    ),
    HitachiFridgeBinarySensorDescription(
        key="spot_cooling_active",
        translation_key="spot_cooling_active",
        device_class=BinarySensorDeviceClass.COLD,
        icon="mdi:coolant-temperature",
        supported_fn=lambda caps: caps.has_spot_cooling,
        is_on_fn=lambda snap: snap.telemetry.quick_or_spot_cooling_in_progress,
    ),
    HitachiFridgeBinarySensorDescription(
        key="quick_freezing_active",
        translation_key="quick_freezing_active",
        device_class=BinarySensorDeviceClass.COLD,
        icon="mdi:snowflake-alert",
        supported_fn=lambda caps: caps.has_quick_freezing_wb,
        is_on_fn=lambda snap: snap.telemetry.quick_mode_in_progress,
    ),
    HitachiFridgeBinarySensorDescription(
        key="selectable_zone_switching",
        translation_key="selectable_zone_switching",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:autorenew",
        supported_fn=lambda caps: caps.has_selectable_zone,
        is_on_fn=lambda snap: snap.telemetry.selectable_zone_switching,
    ),
    HitachiFridgeBinarySensorDescription(
        key="upper_switch_room_switching",
        translation_key="upper_switch_room_switching",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:autorenew",
        supported_fn=lambda caps: caps.has_switch_rooms,
        is_on_fn=lambda snap: snap.telemetry.switch_room_upper_switching,
    ),
    HitachiFridgeBinarySensorDescription(
        key="lower_switch_room_switching",
        translation_key="lower_switch_room_switching",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:autorenew",
        supported_fn=lambda caps: caps.has_switch_rooms,
        is_on_fn=lambda snap: snap.telemetry.switch_room_lower_switching,
    ),
    HitachiFridgeBinarySensorDescription(
        key="electric_drawer",
        translation_key="electric_drawer",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:tray-full",
        supported_fn=lambda caps: caps.has_electric_drawer,
        is_on_fn=lambda snap: snap.telemetry.electric_drawer,
    ),
    HitachiFridgeBinarySensorDescription(
        key="eco_operation_active",
        translation_key="eco_operation_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:leaf-circle-outline",
        is_on_fn=lambda snap: snap.telemetry.eco_operation_active,
    ),
    HitachiFridgeBinarySensorDescription(
        key="under_maintenance",
        translation_key="under_maintenance",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:wrench-clock",
        is_on_fn=lambda snap: snap.telemetry.under_maintenance,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiFridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hitachi Fridge binary sensors supported by each paired model."""
    entities: list[HitachiFridgeBinarySensorEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        caps = coord.capabilities
        for desc in BINARY_SENSOR_DESCRIPTIONS:
            if desc.supported_fn(caps):
                entities.append(HitachiFridgeBinarySensorEntity(coord, desc))
    async_add_entities(entities)


class HitachiFridgeBinarySensorEntity(HitachiFridgeEntity, BinarySensorEntity):
    """Representation of a Hitachi Fridge status binary sensor."""

    entity_description: HitachiFridgeBinarySensorDescription

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        description: HitachiFridgeBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if the indicator is active."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional attributes."""
        if self.coordinator.data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
