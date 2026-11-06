"""Location directory of alerts.in.ua (oblasts, raions, hromadas, cities).

The list lives in locations.json next to this file: [uid, name, type, oblast_uid,
raion_uid]. Types: oblast, raion, hromada, city, standalone (Kyiv, Sevastopol,
Crimea: top level without an oblast above them).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

TOP_TYPES = ("oblast", "standalone")


@dataclass(frozen=True, slots=True)
class Location:
    """One location of the directory."""

    uid: int
    name: str
    type: str
    oblast: int
    raion: int | None

    @property
    def is_top(self) -> bool:
        """Oblast-level location (oblast itself or a standalone city)."""
        return self.type in TOP_TYPES

    def covering_uids(self) -> set[int]:
        """Uids whose alert covers this whole location (itself and parents)."""
        uids = {self.uid, self.oblast}
        if self.raion:
            uids.add(self.raion)
        return uids


def norm_title(title: str | None) -> str:
    """Normalise a location title for fuzzy comparison."""
    if not title:
        return ""
    t = title.lower().replace("’", "'").replace("ʼ", "'").strip()
    for prefix in ("м. ", "м.", "місто "):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    for suffix in (" територіальна громада", " громада", " міська", " селищна", " сільська"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return t


class Directory:
    """Lookup over the bundled list."""

    def __init__(self, items: list[list]) -> None:
        self.by_uid: dict[int, Location] = {}
        for uid, name, typ, oblast, raion in items:
            self.by_uid[int(uid)] = Location(int(uid), name, typ, int(oblast), raion)
        # A city is also listed as the hromada "м. X та ... територіальна громада";
        # an alert on either of them covers both.
        self.twins: dict[int, int] = {}
        for city in self.by_uid.values():
            if city.type != "city":
                continue
            for loc in self.by_uid.values():
                if (
                    loc.type == "hromada"
                    and loc.raion == city.raion
                    and loc.name.startswith(city.name + " та")
                ):
                    self.twins[city.uid] = loc.uid
                    self.twins[loc.uid] = city.uid

    def covering_uids(self, loc: Location) -> set[int]:
        """Uids whose alert covers the whole location (with its city/hromada twin)."""
        uids = loc.covering_uids()
        twin = self.twins.get(loc.uid)
        if twin is not None:
            uids.add(twin)
        return uids

    def get(self, uid: int | str | None) -> Location | None:
        """Location by uid."""
        try:
            return self.by_uid.get(int(uid))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def tops(self) -> list[Location]:
        """Oblasts and standalone cities, sorted by name."""
        return sorted(
            (loc for loc in self.by_uid.values() if loc.is_top),
            key=lambda loc: loc.name,
        )

    def children(self, oblast: int) -> list[Location]:
        """Raions, cities and hromadas of an oblast (without the oblast itself)."""
        return [
            loc
            for loc in self.by_uid.values()
            if loc.oblast == oblast and loc.uid != oblast
        ]

    def label(self, loc: Location) -> str:
        """Human readable label with parents."""
        if loc.is_top:
            return loc.name
        if loc.type == "raion":
            return loc.name
        raion = self.get(loc.raion)
        return f"{loc.name} ({raion.name})" if raion else loc.name


@lru_cache(maxsize=1)
def directory() -> Directory:
    """Load the bundled directory (blocking I/O, call from an executor once)."""
    path = Path(__file__).with_name("locations.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Directory(data["items"])
