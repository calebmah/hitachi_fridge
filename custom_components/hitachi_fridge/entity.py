"""Base CoordinatorEntity for Hitachi Fridge platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HitachiFridgeCoordinator


class HitachiFridgeEntity(CoordinatorEntity[HitachiFridgeCoordinator]):
    """Base entity representing a telemetry point or control on a Hitachi refrigerator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        entity_key: str,
    ) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        appliance = coordinator.appliance
        caps = coordinator.capabilities
        fw_ver = (
            coordinator.data.firmware.version
            if coordinator.data and coordinator.data.firmware
            else None
        )

        self._attr_unique_id = f"{appliance.dst}_{entity_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.dst)},
            name=appliance.nickname,
            manufacturer=MANUFACTURER,
            model=caps.model_name,
            model_id=appliance.dst[:8].upper(),
            serial_number=appliance.dst,
            sw_version=fw_ver,
        )
