"""Event entity: alert started / ended / updated for a region."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertsConfigEntry
from .const import EVENT_TYPES
from .coordinator import AlertsCoordinator, Region, signal_event
from .entity import AlertsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up event entities."""
    coordinator = entry.runtime_data
    for sid, region in coordinator.regions.items():
        async_add_entities([AlertsEvent(coordinator, region)], config_subentry_id=sid)


class AlertsEvent(AlertsEntity, EventEntity):
    """Fires when an alert of the region starts, ends or changes."""

    _attr_event_types = EVENT_TYPES
    _attr_icon = "mdi:alarm-light-outline"

    def __init__(self, coordinator: AlertsCoordinator, region: Region) -> None:
        super().__init__(coordinator, region, "events", "event")

    async def async_added_to_hass(self) -> None:
        """Subscribe to region events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_event(self.coordinator.config_entry.entry_id, self.region.subentry_id),
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._trigger_event(event_type, data)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Events stay available; their state is the time of the last event."""
        return True
