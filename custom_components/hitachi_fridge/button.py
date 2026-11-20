"""Button entities for manual refresh and Local LAN UDP IP rediscovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HitachiFridgeConfigEntry
from .coordinator import HitachiFridgeCoordinator
from .entity import HitachiFridgeEntity


@dataclass(frozen=True, kw_only=True)
class HitachiFridgeButtonDescription(ButtonEntityDescription):
    """Describe a Hitachi Fridge diagnostic button."""

    press_fn: Callable[[HitachiFridgeCoordinator], Awaitable[object]]


BUTTON_DESCRIPTIONS: tuple[HitachiFridgeButtonDescription, ...] = (
    HitachiFridgeButtonDescription(
        key="refresh_status",
        translation_key="refresh_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:refresh",
        press_fn=lambda coord: coord.async_force_full_refresh(),
    ),
    HitachiFridgeButtonDescription(
        key="rediscover_local_ip",
        translation_key="rediscover_local_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lan-pending",
        press_fn=lambda coord: coord.async_rediscover_local_ip(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiFridgeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hitachi Fridge diagnostic buttons."""
    entities: list[HitachiFridgeButtonEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        for desc in BUTTON_DESCRIPTIONS:
            entities.append(HitachiFridgeButtonEntity(coord, desc))
    async_add_entities(entities)


class HitachiFridgeButtonEntity(HitachiFridgeEntity, ButtonEntity):
    """Button entity triggering manual actions on a Hitachi refrigerator."""

    entity_description: HitachiFridgeButtonDescription

    def __init__(
        self,
        coordinator: HitachiFridgeCoordinator,
        description: HitachiFridgeButtonDescription,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Execute the button action."""
        await self.entity_description.press_fn(self.coordinator)
