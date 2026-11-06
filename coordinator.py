"""Polling of active alerts, history, region states and events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AlertsApi,
    AlertsApiError,
    AlertsAuthError,
    AlertsForbiddenError,
    AlertsRateLimitError,
)
from .const import (
    ALERT_AIR_RAID,
    ALERT_TYPES,
    CONF_HISTORY_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_STAT_TYPES,
    CONF_UID,
    DEFAULT_HISTORY_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EV_ENDED,
    EV_PARTIAL_ENDED,
    EV_PARTIAL_STARTED,
    EV_STARTED,
    EV_UPDATED,
    EVENT_BUS,
    HISTORY_MIN_GAP,
    RATE_LIMIT_BACKOFF,
    STAT_PERIODS,
    STATUS_NONE,
    STATUS_PARTIAL,
    SUBENTRY_REGION,
)
from .locations import Directory, Location
from .logic import Alert, RegionState, Summary, region_state, summarize, timeline

_LOGGER = logging.getLogger(__name__)

KEEP = timedelta(days=32)


def signal_event(entry_id: str, subentry_id: str) -> str:
    """Dispatcher signal for events of one region."""
    return f"{DOMAIN}_{entry_id}_{subentry_id}_event"


@dataclass(slots=True)
class Region:
    """One configured region."""

    subentry_id: str
    title: str
    location: Location
    stat_types: list[str]


@dataclass(slots=True)
class RegionData:
    """Everything entities need about one region."""

    state: RegionState
    summary: Summary | None  # None until the oblast history is loaded
    history_loaded: bool
    updated: datetime


@dataclass(slots=True)
class Diagnostics:
    """Counters for diagnostics."""

    last_active_ok: datetime | None = None
    last_active_error: str | None = None
    last_history: dict[int, str] = field(default_factory=dict)
    history_errors: dict[int, str] = field(default_factory=dict)
    active_count: int = 0
    rate_limited_until: datetime | None = None


class AlertsCoordinator(DataUpdateCoordinator[dict[str, RegionData]]):
    """Polls active alerts and keeps a local month of history."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: AlertsApi,
        directory: Directory,
    ) -> None:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.api = api
        self.directory = directory
        self.regions: dict[str, Region] = {}
        self.store: dict[Any, Alert] = {}
        self.history_loaded: set[int] = set()
        self.diag = Diagnostics()
        self._prev_states: dict[str, RegionState] | None = None
        self._history_lock = asyncio.Lock()
        self._last_history_call: datetime | None = None
        self._unsubs: list = []
        self._load_regions()

    # ------------------------------------------------------------ setup

    def _load_regions(self) -> None:
        for sub in self.config_entry.subentries.values():
            if sub.subentry_type != SUBENTRY_REGION:
                continue
            loc = self.directory.get(sub.data.get(CONF_UID))
            if loc is None:
                _LOGGER.warning("Unknown location uid in region %s", sub.title)
                continue
            types = [t for t in sub.data.get(CONF_STAT_TYPES, [ALERT_AIR_RAID]) if t in ALERT_TYPES]
            self.regions[sub.subentry_id] = Region(
                subentry_id=sub.subentry_id,
                title=sub.title,
                location=loc,
                stat_types=types or [ALERT_AIR_RAID],
            )

    @property
    def oblasts(self) -> list[int]:
        """Oblasts whose history is needed."""
        return sorted({r.location.oblast for r in self.regions.values()})

    @callback
    def async_start_history(self) -> None:
        """Load history now (in the background) and then periodically."""
        minutes = int(
            self.config_entry.options.get(CONF_HISTORY_INTERVAL, DEFAULT_HISTORY_INTERVAL)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._history_tick, timedelta(minutes=minutes)
            )
        )
        # Re-evaluate availability (stale data) even while polls keep failing.
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._minute_tick, timedelta(minutes=1)
            )
        )
        self.config_entry.async_create_background_task(
            self.hass, self.async_refresh_history(), f"{DOMAIN} history"
        )

    @callback
    def _minute_tick(self, _now: datetime) -> None:
        if not self.last_update_success:
            self.async_update_listeners()

    @callback
    def async_shutdown_extra(self) -> None:
        """Stop timers."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _history_tick(self, _now: datetime) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self.async_refresh_history(), f"{DOMAIN} history"
        )

    # ------------------------------------------------------------ history

    async def async_refresh_history(self) -> None:
        """Fetch month history for every needed oblast, respecting 2 req/min."""
        async with self._history_lock:
            for oblast in self.oblasts:
                await self._wait_history_slot()
                try:
                    alerts = await self.api.history(oblast)
                except AlertsAuthError:
                    self.config_entry.async_start_reauth(self.hass)
                    return
                except AlertsRateLimitError as err:
                    self.diag.history_errors[oblast] = str(err)
                    await asyncio.sleep(RATE_LIMIT_BACKOFF.total_seconds())
                    continue
                except AlertsApiError as err:
                    self.diag.history_errors[oblast] = str(err)
                    _LOGGER.warning("History of oblast %s failed: %s", oblast, err)
                    continue
                finally:
                    self._last_history_call = dt_util.utcnow()
                self._merge_history(alerts)
                self.history_loaded.add(oblast)
                self.diag.history_errors.pop(oblast, None)
                self.diag.last_history[oblast] = dt_util.utcnow().isoformat()
            self._recompute(fire_events=False)

    async def _wait_history_slot(self) -> None:
        if self._last_history_call is None:
            return
        wait = (self._last_history_call + HISTORY_MIN_GAP - dt_util.utcnow()).total_seconds()
        if wait > 0:
            await asyncio.sleep(wait)

    def _merge_history(self, raw_alerts: list[dict[str, Any]]) -> None:
        for raw in raw_alerts:
            alert = Alert.from_api(raw)
            if alert is None:
                continue
            if alert.end is None:
                old = self.store.get(alert.id)
                if old is not None:
                    # Active polling is fresher than the history snapshot.
                    alert.end = old.end
                elif self.diag.last_active_ok is not None:
                    # Open in history but not active at the last poll: it has ended.
                    alert.end = self.diag.last_active_ok
            self.store[alert.id] = alert
        self._prune()

    def _prune(self) -> None:
        limit = dt_util.utcnow() - KEEP
        for key in [k for k, a in self.store.items() if a.end is not None and a.end < limit]:
            del self.store[key]

    # ------------------------------------------------------------ polling

    async def _async_update_data(self) -> dict[str, RegionData]:
        now = dt_util.utcnow()
        if self.diag.rate_limited_until and now < self.diag.rate_limited_until:
            raise UpdateFailed("Rate limited by alerts.in.ua, waiting")
        try:
            payload = await self.api.active()
        except AlertsAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AlertsRateLimitError as err:
            self.diag.rate_limited_until = now + RATE_LIMIT_BACKOFF
            self.diag.last_active_error = str(err)
            raise UpdateFailed(str(err)) from err
        except AlertsForbiddenError as err:
            self.diag.last_active_error = str(err)
            raise UpdateFailed(str(err)) from err
        except AlertsApiError as err:
            self.diag.last_active_error = str(err)
            raise UpdateFailed(str(err)) from err

        self.diag.last_active_ok = now
        self.diag.last_active_error = None
        self.diag.rate_limited_until = None

        active: dict[Any, Alert] = {}
        for raw in payload["alerts"]:
            alert = Alert.from_api(raw)
            if alert is not None and alert.end is None:
                active[alert.id] = alert
        self.diag.active_count = len(active)

        for key, alert in self.store.items():
            if alert.end is None and key not in active:
                alert.end = now  # ended between polls; history will refine it
        self.store.update(active)
        self._prune()

        return self._compute(now, fire_events=True)

    @callback
    def _recompute(self, fire_events: bool) -> None:
        self.async_set_updated_data(self._compute(dt_util.utcnow(), fire_events))

    def _compute(self, now: datetime, fire_events: bool) -> dict[str, RegionData]:
        active = [a for a in self.store.values() if a.end is None]
        result: dict[str, RegionData] = {}
        states: dict[str, RegionState] = {}
        for sid, region in self.regions.items():
            state = region_state(active, region.location, self.directory)
            states[sid] = state
            loaded = region.location.oblast in self.history_loaded
            intervals = timeline(
                self.store.values(), region.location, self.directory, region.stat_types
            )
            summary = summarize(intervals, now, STAT_PERIODS)
            result[sid] = RegionData(
                state=state,
                summary=summary,
                history_loaded=loaded,
                updated=now,
            )
        if fire_events and self._prev_states is not None:
            for sid, state in states.items():
                prev = self._prev_states.get(sid)
                if prev is not None:
                    self._diff(self.regions[sid], prev, state, now)
        if fire_events or self._prev_states is None:
            self._prev_states = states
        return result

    # ------------------------------------------------------------ events

    def _diff(self, region: Region, old: RegionState, new: RegionState, now: datetime) -> None:
        for alert_type in ALERT_TYPES:
            was, is_ = old.types.get(alert_type, False), new.types.get(alert_type, False)
            if is_ and not was:
                self._fire(region, EV_STARTED, new, alert_type, now)
            elif was and not is_:
                started = old.started.get(alert_type)
                extra: dict[str, Any] = {
                    "started_at": started.isoformat() if started else None,
                    "ended_at": now.isoformat(),
                    "duration_min": round((now - started).total_seconds() / 60)
                    if started
                    else None,
                }
                self._fire(region, EV_ENDED, new, alert_type, now, extra)
        if (
            old.types.get(ALERT_AIR_RAID)
            and new.types.get(ALERT_AIR_RAID)
            and (old.level != new.level or set(old.threat_types) != set(new.threat_types))
        ):
            self._fire(
                region,
                EV_UPDATED,
                new,
                ALERT_AIR_RAID,
                now,
                {
                    "previous_level": old.level,
                    "added_threats": sorted(set(new.threat_types) - set(old.threat_types)),
                    "removed_threats": sorted(set(old.threat_types) - set(new.threat_types)),
                },
            )
        if new.status == STATUS_PARTIAL and old.status == STATUS_NONE:
            self._fire(region, EV_PARTIAL_STARTED, new, None, now)
        elif old.status == STATUS_PARTIAL and new.status == STATUS_NONE:
            self._fire(region, EV_PARTIAL_ENDED, new, None, now)

    def _fire(
        self,
        region: Region,
        event_type: str,
        state: RegionState,
        alert_type: str | None,
        now: datetime,
        extra: dict[str, Any] | None = None,
    ) -> None:
        started = state.started.get(alert_type) if alert_type else None
        data: dict[str, Any] = {
            "region": region.title,
            "uid": region.location.uid,
            "alert_type": alert_type,
            "status": state.status,
            "level": state.level,
            "threats": list(state.threat_types),
            "threat_titles": [t.as_dict()["title"] for t in state.threats],
            "partial_locations": list(state.partial_locations),
            "started_at": started.isoformat() if started else None,
            "at": now.isoformat(),
        }
        if extra:
            data.update(extra)
        _LOGGER.debug("Event %s for %s: %s", event_type, region.title, data)
        async_dispatcher_send(
            self.hass,
            signal_event(self.config_entry.entry_id, region.subentry_id),
            event_type,
            data,
        )
        self.hass.bus.async_fire(EVENT_BUS, {"event_type": event_type, **data})
