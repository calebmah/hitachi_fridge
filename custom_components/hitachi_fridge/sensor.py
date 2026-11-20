"""Sensor entities for Hitachi Fridge telemetry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import HitachiFridgeConfigEntry
from .const import (
    INFO_CODE_DESCRIPTIONS,
    SELECTABLE_ZONE_TEMP_HINTS,
    ModelCapabilities,
)
from .coordinator import HitachiFridgeCoordinator
from .entity import HitachiFridgeEntity
from .models import FridgeCoordinatorSnapshot


@dataclass(frozen=True, kw_only=True)
class HitachiFridgeSensorDescription(SensorEntityDescription):
    """Describe a Hitachi Fridge sensor entity with model-capability gating."""

    supported_fn: Callable[[ModelCapabilities], bool] = lambda _: True
    value_fn: Callable[[FridgeCoordinatorSnapshot], StateType | Any]
    attrs_fn: Callable[[FridgeCoordinatorSnapshot], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[HitachiFridgeSensorDescription, ...] = (
    HitachiFridgeSensorDescription(
        key="door_opens_today",
        translation_key="door_opens_today",
        native_unit_of_measurement="opens",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fridge-outline",
        value_fn=lambda snap: snap.telemetry.door_opens_today,
    ),
    HitachiFridgeSensorDescription(
        key="door_opens_yesterday",
        translation_key="door_opens_yesterday",
        native_unit_of_measurement="opens",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:history",
        value_fn=lambda snap: snap.telemetry.door_opens_yesterday,
        attrs_fn=lambda snap: {
            "ten_day_door_opens": {
                day: stat.door_opens
                for day, stat in snap.door_history.items()
                if stat.door_opens is not None
            }
        },
    ),
    HitachiFridgeSensorDescription(
        key="refrigerator_door_open_duration_today",
        translation_key="refrigerator_door_open_duration_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        supported_fn=lambda caps: caps.has_door_duration_telemetry,
        value_fn=lambda snap: snap.telemetry.door_f_open_seconds_today,
    ),
    HitachiFridgeSensorDescription(
        key="drawer_door_open_duration_today",
        translation_key="drawer_door_open_duration_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        supported_fn=lambda caps: caps.has_door_duration_telemetry,
        value_fn=lambda snap: snap.telemetry.door_d_open_seconds_today,
    ),
    HitachiFridgeSensorDescription(
        key="refrigerator_door_open_duration_yesterday",
        translation_key="refrigerator_door_open_duration_yesterday",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        supported_fn=lambda caps: caps.has_door_duration_telemetry,
        value_fn=lambda snap: snap.telemetry.door_f_open_seconds_yesterday,
        attrs_fn=lambda snap: {
            "ten_day_refrigerator_door_open_seconds": {
                day: stat.refrigerator_open_seconds
                for day, stat in snap.door_history.items()
                if stat.refrigerator_open_seconds is not None
            }
        },
    ),
    HitachiFridgeSensorDescription(
        key="drawer_door_open_duration_yesterday",
        translation_key="drawer_door_open_duration_yesterday",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        supported_fn=lambda caps: caps.has_door_duration_telemetry,
        value_fn=lambda snap: snap.telemetry.door_d_open_seconds_yesterday,
        attrs_fn=lambda snap: {
            "ten_day_drawer_door_open_seconds": {
                day: stat.drawer_open_seconds
                for day, stat in snap.door_history.items()
                if stat.drawer_open_seconds is not None
            }
        },
    ),
    HitachiFridgeSensorDescription(
        key="selectable_zone_mode",
        translation_key="selectable_zone_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["freezer", "soft_freeze", "chill_meat", "refrigerator"],
        icon="mdi:tune-variant",
        supported_fn=lambda caps: caps.has_selectable_zone,
        value_fn=lambda snap: (
            snap.telemetry.selectable_zone_mode.value
            if snap.telemetry.selectable_zone_mode is not None
            else None
        ),
        attrs_fn=lambda snap: (
            {
                "approximate_temperature": SELECTABLE_ZONE_TEMP_HINTS[
                    snap.telemetry.selectable_zone_mode
                ]
            }
            if snap.telemetry.selectable_zone_mode in SELECTABLE_ZONE_TEMP_HINTS
            else {}
        ),
    ),
    HitachiFridgeSensorDescription(
        key="upper_switch_room_mode",
        translation_key="upper_switch_room_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["refrigerator_chilled_veg", "freezer_soft_freeze"],
        icon="mdi:archive-arrow-up-outline",
        supported_fn=lambda caps: caps.has_switch_rooms,
        value_fn=lambda snap: (
            snap.telemetry.switch_room_upper_mode.value
            if snap.telemetry.switch_room_upper_mode is not None
            else None
        ),
    ),
    HitachiFridgeSensorDescription(
        key="lower_switch_room_mode",
        translation_key="lower_switch_room_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["refrigerator_chilled_veg", "freezer_soft_freeze"],
        icon="mdi:archive-arrow-down-outline",
        supported_fn=lambda caps: caps.has_switch_rooms,
        value_fn=lambda snap: (
            snap.telemetry.switch_room_lower_mode.value
            if snap.telemetry.switch_room_lower_mode is not None
            else None
        ),
    ),
    HitachiFridgeSensorDescription(
        key="temperature_control_mode",
        translation_key="temperature_control_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["normal", "fine"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:thermometer-lines",
        value_fn=lambda snap: snap.telemetry.temp_control_mode.value,
    ),
    HitachiFridgeSensorDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
        value_fn=lambda snap: (
            "normal"
            if snap.telemetry.error_code == "000"
            else f"E0{snap.telemetry.error_code}"
        ),
        attrs_fn=lambda snap: {
            "raw_code": snap.telemetry.error_code,
            "recent_history": [
                {
                    "timestamp": item.timestamp,
                    "error_code": (
                        "normal"
                        if item.error_code == "000"
                        else f"E0{item.error_code}"
                    ),
                    "info_code": (
                        "normal"
                        if item.info_code == "000"
                        else f"M0{item.info_code}"
                    ),
                    "info_description": INFO_CODE_DESCRIPTIONS.get(
                        item.info_code, f"Notification {item.info_code}"
                    ),
                }
                for item in snap.alarm_history
            ],
        },
    ),
    HitachiFridgeSensorDescription(
        key="info_code",
        translation_key="info_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information-outline",
        value_fn=lambda snap: (
            "normal"
            if snap.telemetry.info_code == "000"
            else f"M0{snap.telemetry.info_code}"
        ),
        attrs_fn=lambda snap: {
            "raw_code": snap.telemetry.info_code,
            "description": INFO_CODE_DESCRIPTIONS.get(
                snap.telemetry.info_code, f"Notification {snap.telemetry.info_code}"
            ),
        },
    ),
    HitachiFridgeSensorDescription(
        key="connection_transport",
        translation_key="connection_transport",
        device_class=SensorDeviceClass.ENUM,
        options=["local_udp", "cloud_http"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lan-connect",
        value_fn=lambda snap: snap.transport,
        attrs_fn=lambda snap: {"fridge_ip": snap.fridge_ip},
    ),
    HitachiFridgeSensorDescription(
        key="cumulative_drive_time",
        translation_key="cumulative_drive_time",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:counter",
        value_fn=lambda snap: snap.telemetry.integral_drive_time,
        attrs_fn=lambda snap: {"raw_hex": snap.telemetry.integral_drive_time_hex},
    ),
    HitachiFridgeSensorDescription(
        key="appliance_clock",
        translation_key="appliance_clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda snap: snap.telemetry.appliance_timestamp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiFridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hitachi Fridge sensor entities supported by each paired model."""
    entities: list[HitachiFridgeSensorEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        caps = coord.capabilities
        for desc in SENSOR_DESCRIPTIONS:
            if desc.supported_fn(caps):
                entities.append(HitachiFridgeSensorEntity(coord, desc))
    async_add_entities(entities)


class HitachiFridgeSensorEntity(HitachiFridgeEntity, SensorEntity):
    """Representation of a Hitachi Fridge telemetry sensor."""

    entity_description: HitachiFridgeSensorDescription

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        description: HitachiFridgeSensorDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | Any:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional state attributes."""
        if self.coordinator.data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
