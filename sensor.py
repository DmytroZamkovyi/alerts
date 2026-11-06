"""Sensors: status, level, threats, durations and statistics of a region."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
from homeassistant.util import dt as dt_util

from . import AlertsConfigEntry
from .const import ALERT_TITLES_UK, LEVEL_NONE, LEVELS, STAT_PERIODS, STATUSES
from .coordinator import AlertsCoordinator, Region, RegionData
from .entity import AlertsEntity


def _minutes(td) -> float | None:
    return None if td is None else round(td.total_seconds() / 60, 1)


@dataclass(frozen=True, kw_only=True)
class AlertsSensorDescription(SensorEntityDescription):
    """Sensor description with value and attribute functions."""

    value_fn: Callable[[RegionData, datetime], Any]
    attrs_fn: Callable[[RegionData, Region], dict[str, Any]] | None = None
    needs_history: bool = False


def _status_attrs(d: RegionData, region: Region) -> dict[str, Any]:
    st = d.state
    return {
        "active_types": [t for t, on in st.types.items() if on],
        "active_titles": [ALERT_TITLES_UK.get(t, t) for t, on in st.types.items() if on],
        "covering_locations": list(st.covering_titles),
        "partial_locations": list(st.partial_locations),
        "location_uid": region.location.uid,
    }


def _threat_attrs(d: RegionData, region: Region) -> dict[str, Any]:
    st = d.state
    return {
        "threats": list(st.threat_types),
        "titles": [t.as_dict()["title"] for t in st.threats],
        "details": [t.as_dict() for t in st.threats],
        "text": ", ".join(t.as_dict()["title"] for t in st.threats),
    }


def _stat_types_attrs(d: RegionData, region: Region) -> dict[str, Any]:
    return {"alert_types": list(region.stat_types)}


def _since_duration(d: RegionData, now: datetime) -> float | None:
    s = d.summary
    if s is None or s.since is None:
        return None
    if not s.active and not d.history_loaded:
        return None
    return _minutes(now - s.since)


DESCRIPTIONS: list[AlertsSensorDescription] = [
    AlertsSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        value_fn=lambda d, now: d.state.status,
        attrs_fn=_status_attrs,
    ),
    AlertsSensorDescription(
        key="level",
        device_class=SensorDeviceClass.ENUM,
        options=LEVELS,
        value_fn=lambda d, now: d.state.level or LEVEL_NONE,
    ),
    AlertsSensorDescription(
        key="threats",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, now: len(d.state.threats),
        attrs_fn=_threat_attrs,
    ),
    AlertsSensorDescription(
        key="alert_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, now: d.summary.since
        if d.summary and d.summary.active
        else None,
        attrs_fn=_stat_types_attrs,
    ),
    AlertsSensorDescription(
        key="state_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_since_duration,
        attrs_fn=_stat_types_attrs,
    ),
    AlertsSensorDescription(
        key="last_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, now: d.summary.last_end if d.summary else None,
        attrs_fn=lambda d, r: {
            "started_at": d.summary.last_start.isoformat()
            if d.summary and d.summary.last_start
            else None,
            "alert_types": list(r.stat_types),
        },
        needs_history=True,
    ),
    AlertsSensorDescription(
        key="last_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda d, now: _minutes(d.summary.last_duration) if d.summary else None,
        attrs_fn=_stat_types_attrs,
        needs_history=True,
    ),
]

for _period in STAT_PERIODS:
    DESCRIPTIONS.extend(
        [
            AlertsSensorDescription(
                key=f"count_{_period}",
                state_class=SensorStateClass.MEASUREMENT,
                value_fn=lambda d, now, p=_period: d.summary.stats[p].count
                if d.summary
                else None,
                attrs_fn=_stat_types_attrs,
                needs_history=True,
            ),
            AlertsSensorDescription(
                key=f"duration_{_period}",
                device_class=SensorDeviceClass.DURATION,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=UnitOfTime.MINUTES,
                suggested_unit_of_measurement=UnitOfTime.HOURS,
                suggested_display_precision=1,
                value_fn=lambda d, now, p=_period: _minutes(d.summary.stats[p].duration)
                if d.summary
                else None,
                attrs_fn=lambda d, r, p=_period: {
                    "alert_types": list(r.stat_types),
                    "longest_min": _minutes(d.summary.stats[p].longest) if d.summary else None,
                },
                needs_history=True,
            ),
        ]
    )

DIAG_DESCRIPTION = AlertsSensorDescription(
    key="history_updated",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda d, now: None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    for sid, region in coordinator.regions.items():
        entities: list[SensorEntity] = [
            AlertsSensor(coordinator, region, desc) for desc in DESCRIPTIONS
        ]
        entities.append(HistoryUpdatedSensor(coordinator, region, DIAG_DESCRIPTION))
        async_add_entities(entities, config_subentry_id=sid)


class AlertsSensor(AlertsEntity, SensorEntity):
    """Value computed from region data."""

    entity_description: AlertsSensorDescription

    def __init__(
        self,
        coordinator: AlertsCoordinator,
        region: Region,
        description: AlertsSensorDescription,
    ) -> None:
        super().__init__(coordinator, region, description.key, "sensor")
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Current value."""
        data = self.region_data
        if data is None:
            return None
        if self.entity_description.needs_history and not data.history_loaded:
            return None
        return self.entity_description.value_fn(data, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes."""
        data = self.region_data
        if data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(data, self.region)


class HistoryUpdatedSensor(AlertsSensor):
    """When the oblast history was last loaded."""

    @property
    def native_value(self) -> datetime | None:
        """Time of the last successful history load."""
        raw = self.coordinator.diag.last_history.get(self.region.location.oblast)
        return dt_util.parse_datetime(raw) if raw else None
