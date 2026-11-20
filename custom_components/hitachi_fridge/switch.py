"""Switch entities for Hitachi Fridge controls, firmware auto-update, and notifications."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HitachiFridgeConfigEntry
from .const import (
    PUSH_NOTIFICATION_SWITCH_KEYS,
    CtrlCode,
    ModelCapabilities,
    ModelFamily,
)
from .coordinator import HitachiFridgeCoordinator
from .entity import HitachiFridgeEntity
from .models import FridgeTelemetry


@dataclass(frozen=True, kw_only=True)
class HitachiControlSwitchDescription(SwitchEntityDescription):
    """Describe an appliance `CTRLINS` boolean switch."""

    supported_fn: Callable[[ModelCapabilities], bool]
    ctrl_code_fn: Callable[[ModelCapabilities], CtrlCode]
    is_on_fn: Callable[[FridgeTelemetry, ModelCapabilities], bool]


CONTROL_SWITCH_DESCRIPTIONS: tuple[HitachiControlSwitchDescription, ...] = (
    HitachiControlSwitchDescription(
        key="energy_saver",
        translation_key="energy_saver",
        icon="mdi:leaf",
        supported_fn=lambda caps: caps.has_energy_saver,
        ctrl_code_fn=lambda _: CtrlCode.ENERGY_SAVER,
        is_on_fn=lambda tel, _: tel.energy_saving,
    ),
    HitachiControlSwitchDescription(
        key="ice_maker",
        translation_key="ice_maker",
        icon="mdi:cube-outline",
        supported_fn=lambda caps: caps.ice_maker_modes == 2,
        ctrl_code_fn=lambda _: CtrlCode.ICE_MAKER,
        is_on_fn=lambda tel, _: tel.ice_maker_raw == 1,
    ),
    HitachiControlSwitchDescription(
        key="vacuum_compartment_switch",
        translation_key="vacuum_compartment_switch",
        icon="mdi:air-purifier",
        supported_fn=lambda caps: caps.vacuum_modes == 2,
        ctrl_code_fn=lambda _: CtrlCode.VACUUM_COMPARTMENT,
        is_on_fn=lambda tel, _: tel.vacuum_mode_raw == 1,
    ),
    HitachiControlSwitchDescription(
        key="quick_cooling",
        translation_key="quick_cooling",
        icon="mdi:snowflake",
        supported_fn=lambda caps: caps.has_quick_cooling_wb or caps.has_quick_cooling_gwc,
        ctrl_code_fn=lambda caps: (
            CtrlCode.QUICK_FREEZING_OR_SPEED
            if caps.family == ModelFamily.JP_GWC
            else CtrlCode.QUICK_COOLING_OR_SPOT
        ),
        is_on_fn=lambda tel, caps: (
            tel.quick_cooling_gwc
            if caps.family == ModelFamily.JP_GWC
            else tel.quick_cooling_wb
        ),
    ),
    HitachiControlSwitchDescription(
        key="quick_freezing",
        translation_key="quick_freezing",
        icon="mdi:snowflake-melt",
        supported_fn=lambda caps: caps.has_quick_freezing_wb,
        ctrl_code_fn=lambda _: CtrlCode.QUICK_FREEZING_OR_SPEED,
        is_on_fn=lambda tel, _: tel.quick_freezing_wb,
    ),
    HitachiControlSwitchDescription(
        key="spot_cooling",
        translation_key="spot_cooling",
        icon="mdi:coolant-temperature",
        supported_fn=lambda caps: caps.has_spot_cooling,
        ctrl_code_fn=lambda _: CtrlCode.QUICK_COOLING_OR_SPOT,
        is_on_fn=lambda tel, _: tel.spot_cooling,
    ),
    HitachiControlSwitchDescription(
        key="speed_cooling",
        translation_key="speed_cooling",
        icon="mdi:snowflake-fast",
        supported_fn=lambda caps: caps.has_speed_cooling,
        ctrl_code_fn=lambda _: CtrlCode.QUICK_FREEZING_OR_SPEED,
        is_on_fn=lambda tel, _: tel.speed_cooling,
    ),
    HitachiControlSwitchDescription(
        key="vegetable_compartment",
        translation_key="vegetable_compartment",
        icon="mdi:sprout",
        supported_fn=lambda caps: caps.has_vegetable_compartment,
        ctrl_code_fn=lambda _: CtrlCode.VEGETABLE_COMPARTMENT,
        is_on_fn=lambda tel, _: tel.vegetable_compartment,
    ),
    HitachiControlSwitchDescription(
        key="control_lock",
        translation_key="control_lock",
        icon="mdi:lock-outline",
        entity_category=EntityCategory.CONFIG,
        supported_fn=lambda caps: caps.has_control_lock,
        ctrl_code_fn=lambda _: CtrlCode.CONTROL_LOCK,
        is_on_fn=lambda tel, _: tel.control_lock,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiFridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hitachi Fridge switch entities supported by each paired model."""
    entities: list[SwitchEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        caps = coord.capabilities
        for desc in CONTROL_SWITCH_DESCRIPTIONS:
            if desc.supported_fn(caps):
                entities.append(HitachiControlSwitchEntity(coord, desc))

        if coord.cloud_api.can_auto_renew or coord.cloud_api.session_data is not None:
            entities.append(HitachiFirmwareAutoUpdateSwitch(coord))
            for push_id in caps.supported_push_ids:
                if push_id in PUSH_NOTIFICATION_SWITCH_KEYS:
                    entities.append(HitachiPushNotificationSwitch(coord, push_id))

    async_add_entities(entities)


class HitachiControlSwitchEntity(HitachiFridgeEntity, SwitchEntity):
    """Switch entity executing Local UDP / Cloud `CTRLINS` commands."""

    entity_description: HitachiControlSwitchDescription

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        description: HitachiControlSwitchDescription,
    ) -> None:
        """Initialize the appliance control switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if the refrigerator feature is enabled."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.is_on_fn(
            self.coordinator.data.telemetry,
            self.coordinator.capabilities,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the refrigerator feature."""
        ctrl_code = self.entity_description.ctrl_code_fn(self.coordinator.capabilities)
        await self.coordinator.async_send_control(ctrl_code, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the refrigerator feature."""
        ctrl_code = self.entity_description.ctrl_code_fn(self.coordinator.capabilities)
        await self.coordinator.async_send_control(ctrl_code, 0)


class HitachiFirmwareAutoUpdateSwitch(HitachiFridgeEntity, SwitchEntity):
    """Switch controlling automatic firmware updates (`CMD=FWSETTING`)."""

    _attr_translation_key = "firmware_auto_update"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: HitachiFridgeCoordinator) -> None:
        """Initialize the firmware auto-update switch."""
        super().__init__(coordinator, "firmware_auto_update")

    @property
    def available(self) -> bool:
        """Return True when firmware status has been retrieved from Cloud."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.firmware is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if automatic firmware updates are enabled."""
        if self.coordinator.data is None or self.coordinator.data.firmware is None:
            return None
        return self.coordinator.data.firmware.auto_update_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable automatic firmware updates."""
        await self.coordinator.async_set_firmware_auto_update(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable automatic firmware updates."""
        await self.coordinator.async_set_firmware_auto_update(False)


class HitachiPushNotificationSwitch(HitachiFridgeEntity, SwitchEntity):
    """Switch controlling a Hitachi Cloud push notification category (`CMD=PUSHREG`)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:bell-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: HitachiFridgeCoordinator, push_id: str) -> None:
        """Initialize the push notification switch."""
        t_key = PUSH_NOTIFICATION_SWITCH_KEYS[push_id]
        super().__init__(coordinator, t_key)
        self._push_id = push_id
        self._attr_translation_key = t_key

    @property
    def available(self) -> bool:
        """Return True when push notification preferences are loaded."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.disabled_push_ids is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if notifications for this category are enabled (not muted)."""
        if (
            self.coordinator.data is None
            or self.coordinator.data.disabled_push_ids is None
        ):
            return None
        return self._push_id not in self.coordinator.data.disabled_push_ids

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable push notifications for this category."""
        await self.coordinator.async_set_push_notification(self._push_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Mute push notifications for this category."""
        await self.coordinator.async_set_push_notification(self._push_id, False)
