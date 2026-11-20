"""Update entity for Hitachi Fridge firmware status and installation (`CMD=FWINFO` / `FWEXE`)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HitachiFridgeConfigEntry
from .coordinator import HitachiFridgeCoordinator
from .entity import HitachiFridgeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiFridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hitachi Fridge firmware update entities when Cloud API is active."""
    entities: list[HitachiFridgeFirmwareUpdateEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        if coord.cloud_api.can_auto_renew or coord.cloud_api.session_data is not None:
            entities.append(HitachiFridgeFirmwareUpdateEntity(coord))
    async_add_entities(entities)


class HitachiFridgeFirmwareUpdateEntity(HitachiFridgeEntity, UpdateEntity):
    """Representation of Hitachi refrigerator firmware update status."""

    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, coordinator: HitachiFridgeCoordinator) -> None:
        """Initialize the firmware update entity."""
        super().__init__(coordinator, "firmware")

    @property
    def available(self) -> bool:
        """Return True when firmware info has been fetched from Hitachi Cloud."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.firmware is not None
        )

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed firmware version (`FWVER`)."""
        if self.coordinator.data is None or self.coordinator.data.firmware is None:
            return None
        return self.coordinator.data.firmware.version

    @property
    def latest_version(self) -> str | None:
        """Return the latest firmware version indicator."""
        if self.coordinator.data is None or self.coordinator.data.firmware is None:
            return None
        fw = self.coordinator.data.firmware
        if fw.update_available:
            return f"{fw.version} (update available)"
        return fw.version

    @property
    def in_progress(self) -> bool:
        """Return True if a firmware update is currently installing (`FWSTS == '2'`)."""
        if self.coordinator.data is None or self.coordinator.data.firmware is None:
            return False
        return self.coordinator.data.firmware.update_in_progress

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the available refrigerator firmware update (`CMD=FWEXE`)."""
        await self.coordinator.async_install_firmware()
