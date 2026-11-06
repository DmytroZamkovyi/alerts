"""Base entity: one device per configured region."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DOMAIN
from .coordinator import AlertsCoordinator, Region, RegionData

STALE_AFTER = timedelta(minutes=10)


class AlertsEntity(CoordinatorEntity[AlertsCoordinator]):
    """Entity bound to one region."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: AlertsCoordinator, region: Region, key: str, domain: str) -> None:
        super().__init__(coordinator)
        self.region = region
        entry_id = coordinator.config_entry.entry_id
        uid = region.location.uid
        self._attr_unique_id = f"{entry_id}_{uid}_{key}"
        self._attr_translation_key = key
        # Stable English entity ids: <domain>.alerts_<uid>_<key>
        self.entity_id = f"{domain}.alerts_{uid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{uid}")},
            name=region.title,
            manufacturer="alerts.in.ua",
            model=coordinator.directory.label(region.location),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://alerts.in.ua/",
        )

    @property
    def region_data(self) -> RegionData | None:
        """Current data of this region."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.region.subentry_id)

    @property
    def available(self) -> bool:
        """Available while data is fresh; single failed polls do not flap the state."""
        last_ok = self.coordinator.diag.last_active_ok
        if self.region_data is None or last_ok is None:
            return False
        return dt_util.utcnow() - last_ok < STALE_AFTER
