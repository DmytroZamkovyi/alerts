"""Binary sensors: one per alert type for every region."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertsConfigEntry
from .const import ALERT_AIR_RAID, ALERT_TITLES_UK, ALERT_TYPES
from .coordinator import AlertsCoordinator, Region
from .entity import AlertsEntity

ICONS = {
    "air_raid": "mdi:alarm-light",
    "artillery_shelling": "mdi:bomb",
    "urban_fights": "mdi:shield-alert",
    "chemical": "mdi:chemical-weapon",
    "nuclear": "mdi:radioactive",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    for sid, region in coordinator.regions.items():
        async_add_entities(
            [AlertTypeSensor(coordinator, region, t) for t in ALERT_TYPES],
            config_subentry_id=sid,
        )


class AlertTypeSensor(AlertsEntity, BinarySensorEntity):
    """Alert of one type covers the region."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: AlertsCoordinator, region: Region, alert_type: str) -> None:
        super().__init__(coordinator, region, alert_type, "binary_sensor")
        self.alert_type = alert_type
        self._attr_icon = ICONS.get(alert_type)

    @property
    def is_on(self) -> bool | None:
        """Alert is active for the whole region."""
        data = self.region_data
        return None if data is None else data.state.types.get(self.alert_type, False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details of the active alert."""
        data = self.region_data
        if data is None:
            return {}
        st = data.state
        started = st.started.get(self.alert_type)
        attrs: dict[str, Any] = {
            "title": ALERT_TITLES_UK.get(self.alert_type, self.alert_type),
            "started_at": started.isoformat() if started else None,
            "location_uid": self.region.location.uid,
        }
        if self.alert_type == ALERT_AIR_RAID:
            attrs.update(
                {
                    "level": st.level,
                    "threats": list(st.threat_types),
                    "threat_titles": [t.as_dict()["title"] for t in st.threats],
                    "threat_details": [t.as_dict() for t in st.threats],
                    "status": st.status,
                    "covering_locations": list(st.covering_titles),
                    "partial_locations": list(st.partial_locations),
                    "notes": list(st.notes),
                }
            )
        return attrs
