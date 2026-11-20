"""Text entity for configuring the Hitachi refrigerator nickname."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
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
    """Set up Hitachi Fridge nickname text entities when Cloud API is active."""
    entities: list[HitachiApplianceNicknameText] = []
    for coord in entry.runtime_data.coordinators.values():
        if coord.cloud_api.can_auto_renew or coord.cloud_api.session_data is not None:
            entities.append(HitachiApplianceNicknameText(coord))
    async_add_entities(entities)


class HitachiApplianceNicknameText(HitachiFridgeEntity, TextEntity):
    """Editable refrigerator nickname (`CMD=SETDEVNAME`, max 16 chars)."""

    _attr_translation_key = "appliance_nickname"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:rename-box"
    _attr_native_min = 1
    _attr_native_max = 16
    _attr_pattern = r"^[^*/()]{1,16}$"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: HitachiFridgeCoordinator) -> None:
        """Initialize the appliance nickname text entity."""
        super().__init__(coordinator, "appliance_nickname")

    @property
    def native_value(self) -> str | None:
        """Return the current refrigerator nickname."""
        if self.coordinator.data is not None:
            return self.coordinator.data.nickname
        return self.coordinator.appliance.nickname

    async def async_set_value(self, value: str) -> None:
        """Update the refrigerator nickname in Hitachi Cloud."""
        await self.coordinator.async_set_nickname(value)
