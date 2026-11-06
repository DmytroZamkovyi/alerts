"""Pure logic: parsing alerts, region state, timeline and statistics.

No Home Assistant imports here, so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .const import (
    ALERT_AIR_RAID,
    ALERT_TYPES,
    STATUS_ACTIVE,
    STATUS_NONE,
    STATUS_PARTIAL,
    THREAT_TITLES_UK,
)
from .locations import Directory, Location, norm_title

LEVEL_RANK = {"red": 2, "yellow": 1}

COVER = "cover"
INSIDE = "inside"


def parse_time(value: Any) -> datetime | None:
    """Parse the API timestamp (UTC, '2024-01-01T10:00:00.000Z')."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Threat:
    """One threat inside an alert."""

    type: str
    level: str | None
    started: datetime | None
    source: str | None

    def as_dict(self) -> dict[str, Any]:
        """Attribute form."""
        return {
            "type": self.type,
            "title": THREAT_TITLES_UK.get(self.type, self.type),
            "level": self.level,
            "started_at": self.started.isoformat() if self.started else None,
            "source_message": self.source,
        }


@dataclass(slots=True)
class Alert:
    """One alert from the API."""

    id: int | str
    uid: int | None
    title: str
    location_type: str | None
    oblast_uid: int | None
    raion_title: str | None
    type: str
    level: str | None
    start: datetime
    end: datetime | None
    threats: tuple[Threat, ...] = ()
    notes: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Alert | None:
        """Build from an API dict; None when unusable."""
        start = parse_time(raw.get("started_at"))
        if start is None or raw.get("id") is None:
            return None

        def _int(v: Any) -> int | None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        threats = tuple(
            Threat(
                type=str(t.get("threat_type") or "unknown"),
                level=t.get("level"),
                started=parse_time(t.get("started_at")),
                source=t.get("source_message"),
            )
            for t in (raw.get("threats") or [])
            if isinstance(t, dict)
        )
        return cls(
            id=raw["id"],
            uid=_int(raw.get("location_uid")),
            title=str(raw.get("location_title") or ""),
            location_type=raw.get("location_type"),
            oblast_uid=_int(raw.get("location_oblast_uid")),
            raion_title=raw.get("location_raion"),
            type=str(raw.get("alert_type") or ALERT_AIR_RAID),
            level=raw.get("alert_level"),
            start=start,
            end=parse_time(raw.get("finished_at")),
            threats=threats,
            notes=raw.get("notes") or None,
        )


def relation(alert: Alert, region: Location, directory: Directory) -> str | None:
    """How an alert relates to a region.

    COVER: the alert is on the region itself or on a location that contains it.
    INSIDE: the alert is on a part of the region only.
    """
    if alert.uid is not None and alert.uid in directory.covering_uids(region):
        return COVER
    loc = directory.get(alert.uid)
    if loc is not None:
        if (
            loc.oblast == region.oblast
            and not loc.is_top
            and not region.is_top
            and region.type != "raion"
            and loc.type != "raion"
            and norm_title(loc.name) == norm_title(region.name)
        ):
            # The same town listed as both city and hromada.
            return COVER
        if region.is_top and loc.oblast == region.uid and loc.uid != region.uid:
            return INSIDE
        if region.type == "raion" and loc.raion == region.uid:
            return INSIDE
        return None

    # Unknown uid: fall back to titles within the same oblast.
    oblast = alert.oblast_uid
    if oblast is None or oblast != region.oblast:
        return None
    title = norm_title(alert.title)
    if region.is_top:
        return INSIDE
    if title and title == norm_title(region.name):
        return COVER
    if region.type == "raion":
        if norm_title(alert.raion_title) == norm_title(region.name):
            return INSIDE
        return None
    raion = directory.get(region.raion)
    if raion and alert.location_type == "raion" and title == norm_title(raion.name):
        return COVER
    return None


@dataclass(slots=True)
class RegionState:
    """Current state of one region."""

    status: str = STATUS_NONE
    types: dict[str, bool] = field(default_factory=lambda: {t: False for t in ALERT_TYPES})
    level: str | None = None  # air raid level: red / yellow / None
    threats: tuple[Threat, ...] = ()
    started: dict[str, datetime] = field(default_factory=dict)  # by alert type
    partial_locations: tuple[str, ...] = ()
    covering_titles: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def threat_types(self) -> tuple[str, ...]:
        """Threat codes."""
        return tuple(t.type for t in self.threats)


def region_state(
    alerts: Iterable[Alert], region: Location, directory: Directory
) -> RegionState:
    """Compute the current state of a region from active alerts."""
    state = RegionState()
    covering: list[Alert] = []
    inside: list[Alert] = []
    for alert in alerts:
        if alert.end is not None:
            continue
        rel = relation(alert, region, directory)
        if rel == COVER:
            covering.append(alert)
        elif rel == INSIDE:
            inside.append(alert)

    if covering:
        state.status = STATUS_ACTIVE
    elif inside:
        state.status = STATUS_PARTIAL

    threats: dict[str, Threat] = {}
    for alert in covering:
        if alert.type not in state.types:
            state.types[alert.type] = False
        state.types[alert.type] = True
        prev = state.started.get(alert.type)
        if prev is None or alert.start < prev:
            state.started[alert.type] = alert.start
        if alert.type == ALERT_AIR_RAID:
            level = alert.level or "red"
            if LEVEL_RANK.get(level, 0) > LEVEL_RANK.get(state.level or "", 0):
                state.level = level
            for threat in alert.threats:
                old = threats.get(threat.type)
                if old is None or LEVEL_RANK.get(threat.level or "", 0) > LEVEL_RANK.get(
                    old.level or "", 0
                ):
                    threats[threat.type] = threat
    state.threats = tuple(sorted(threats.values(), key=lambda t: t.type))
    state.covering_titles = tuple(sorted({a.title for a in covering if a.title}))
    state.partial_locations = tuple(sorted({a.title for a in inside if a.title}))
    state.notes = tuple(sorted({str(a.notes) for a in covering if a.notes}))
    return state


# ---------------------------------------------------------------- timeline


@dataclass(frozen=True, slots=True)
class Interval:
    """Merged alert interval; end None while it lasts."""

    start: datetime
    end: datetime | None

    def duration(self, now: datetime) -> timedelta:
        """Length up to now."""
        return (self.end or now) - self.start


def timeline(
    alerts: Iterable[Alert],
    region: Location,
    directory: Directory,
    types: Iterable[str],
) -> list[Interval]:
    """Merged intervals of alerts covering the region, of the given types."""
    wanted = set(types)
    spans: list[tuple[datetime, datetime | None]] = []
    for alert in alerts:
        if alert.type not in wanted:
            continue
        if relation(alert, region, directory) != COVER:
            continue
        if alert.end is not None and alert.end <= alert.start:
            continue
        spans.append((alert.start, alert.end))
    spans.sort(key=lambda s: s[0])

    merged: list[Interval] = []
    cur_start: datetime | None = None
    cur_end: datetime | None = None
    open_now = False
    for start, end in spans:
        if cur_start is None:
            cur_start, cur_end, open_now = start, end, end is None
            continue
        if open_now or (cur_end is not None and start <= cur_end):
            if end is None:
                open_now = True
            elif not open_now and cur_end is not None and end > cur_end:
                cur_end = end
            continue
        merged.append(Interval(cur_start, None if open_now else cur_end))
        cur_start, cur_end, open_now = start, end, end is None
    if cur_start is not None:
        merged.append(Interval(cur_start, None if open_now else cur_end))
    return merged


@dataclass(slots=True)
class Stats:
    """Statistics for one period."""

    count: int
    duration: timedelta
    longest: timedelta


def period_stats(intervals: list[Interval], now: datetime, period: timedelta) -> Stats:
    """Count and total duration of intervals overlapping [now - period, now]."""
    lo = now - period
    count = 0
    total = timedelta()
    longest = timedelta()
    for iv in intervals:
        end = iv.end or now
        if end <= lo or iv.start >= now:
            continue
        count += 1
        part = min(end, now) - max(iv.start, lo)
        total += part
        longest = max(longest, end - iv.start)
    return Stats(count, total, longest)


@dataclass(slots=True)
class Summary:
    """Timeline-derived values of a region."""

    active: bool
    since: datetime | None  # start of current alert, or end of the last one
    last_start: datetime | None
    last_end: datetime | None
    last_duration: timedelta | None
    stats: dict[str, Stats]


def summarize(
    intervals: list[Interval], now: datetime, periods: dict[str, timedelta]
) -> Summary:
    """Current state duration, last alert and period statistics."""
    current = intervals[-1] if intervals and intervals[-1].end is None else None
    finished = [iv for iv in intervals if iv.end is not None]
    last = finished[-1] if finished else None
    return Summary(
        active=current is not None,
        since=current.start if current else (last.end if last else None),
        last_start=last.start if last else None,
        last_end=last.end if last else None,
        last_duration=(last.end - last.start) if last and last.end else None,
        stats={key: period_stats(intervals, now, p) for key, p in periods.items()},
    )
