"""ZIP codes, distances and areas.

ZIP lookups are offline: the `zipcodes` package ships the US ZIP list with each
ZIP's center point, so no address or ZIP leaves your PC to be geocoded.
Distances are straight-line miles from the ZIP's center, which is close enough
to decide whether a store is "inside 15 miles".
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

EARTH_MILES = 3958.8


@dataclass(frozen=True)
class Area:
    name: str
    zip: str
    radius: float
    lat: float | None = None
    lon: float | None = None
    webhook: str = ""        # optional Discord webhook just for this area

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None


def clean_zip(value) -> str:
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return m.group(1) if m else ""


@lru_cache(maxsize=4096)
def zip_point(zip_code: str) -> tuple[float, float] | None:
    """(lat, lon) for a US ZIP, or None if unknown or the package is missing."""
    z = clean_zip(zip_code)
    if not z:
        return None
    try:
        import zipcodes  # type: ignore
        rows = zipcodes.matching(z)
    except Exception:
        return None
    for row in rows or []:
        lat = row.get("lat", row.get("latitude"))
        lon = row.get("long", row.get("lng", row.get("longitude")))
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            continue
    return None


def zip_place(zip_code: str) -> str:
    """'Sparks, NV' style label for a ZIP, when known."""
    try:
        import zipcodes  # type: ignore
        rows = zipcodes.matching(clean_zip(zip_code))
        if rows:
            return f"{rows[0].get('city', '').title()}, {rows[0].get('state', '')}".strip(", ")
    except Exception:
        pass
    return ""


def geocoder_ready() -> bool:
    return zip_point("10001") is not None


def miles(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_MILES * math.asin(min(1.0, math.sqrt(h)))


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Compass bearing from a to b in degrees (0 = north)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def build_areas(raw_cfg: dict) -> list[Area]:
    """Areas from config. Falls back to the older single location.zip setting."""
    out: list[Area] = []
    for i, a in enumerate(raw_cfg.get("areas") or []):
        if not isinstance(a, dict) or a.get("enabled") is False:
            continue
        z = clean_zip(a.get("zip"))
        if not z:
            continue
        pt = zip_point(z)
        out.append(Area(str(a.get("name") or f"Area {i + 1}"), z, float(a.get("radius_miles") or 15),
                        pt[0] if pt else None, pt[1] if pt else None, str(a.get("webhook") or "").strip()))
    if not out:
        loc = raw_cfg.get("location") or {}
        z = clean_zip(loc.get("zip"))
        if z:
            pt = zip_point(z)
            out.append(Area("Home", z, float(loc.get("radius_miles") or 25),
                            pt[0] if pt else None, pt[1] if pt else None))
    return out


def place_point(lat=None, lon=None, zip_code: str = "") -> tuple[float, float] | None:
    try:
        if lat not in (None, "") and lon not in (None, ""):
            return float(lat), float(lon)
    except (TypeError, ValueError):
        pass
    return zip_point(zip_code) if zip_code else None


def nearest_area(point: tuple[float, float] | None, areas: list[Area],
                 fallback_distance: float | None = None, fallback_area: Area | None = None
                 ) -> tuple[Area | None, float | None]:
    """The closest area whose radius contains the point, and the distance to it.

    When the point is unknown, the retailer's own distance from the area it was
    asked about is used instead (fallback_distance + fallback_area).
    """
    best: tuple[Area | None, float | None] = (None, None)
    if point:
        for area in areas:
            if not area.located:
                continue
            d = miles(point, (area.lat, area.lon))  # type: ignore[arg-type]
            if d is not None and d <= area.radius and (best[1] is None or d < best[1]):
                best = (area, d)
        if best[0] or any(a.located for a in areas):
            return best
    if fallback_area is not None and fallback_distance is not None and fallback_distance <= fallback_area.radius:
        return fallback_area, fallback_distance
    return best
