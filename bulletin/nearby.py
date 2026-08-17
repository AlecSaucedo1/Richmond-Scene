from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .political_quotes import D3_PROXY, build_quote_analysis

SOURCE_ORDER = ("businesses", "permits", "service_requests", "police")
SOURCE_LABELS = {
    "businesses": "Business & storefronts",
    "permits": "Development & housing",
    "service_requests": "Streets & city services",
    "police": "Public safety",
}
DATASF_NEIGHBORHOOD_GEOJSON = "https://data.sfgov.org/resource/j2bu-swwd.geojson"
SF_BOUNDS = {"min_lat": 37.60, "max_lat": 37.86, "min_lon": -122.56, "max_lon": -122.31}

NEIGHBORHOOD_CENTERS: dict[str, tuple[float, float]] = {
    "Bayview Hunters Point": (37.7304, -122.3844), "Bernal Heights": (37.7412, -122.4146),
    "Castro/Upper Market": (37.7609, -122.4350), "Chinatown": (37.7941, -122.4078),
    "Excelsior": (37.7212, -122.4323), "Financial District/South Beach": (37.7900, -122.3970),
    "Glen Park": (37.7330, -122.4332), "Golden Gate Park": (37.7694, -122.4862),
    "Haight Ashbury": (37.7692, -122.4481), "Hayes Valley": (37.7764, -122.4242),
    "Inner Richmond": (37.7804, -122.4660), "Inner Sunset": (37.7615, -122.4664),
    "Japantown": (37.7854, -122.4294), "Lakeshore": (37.7305, -122.4935),
    "Lincoln Park": (37.7842, -122.4949), "Lone Mountain/USF": (37.7795, -122.4519),
    "Marina": (37.8030, -122.4360), "McLaren Park": (37.7194, -122.4194),
    "Mission": (37.7599, -122.4148), "Mission Bay": (37.7716, -122.3875),
    "Nob Hill": (37.7930, -122.4161), "Noe Valley": (37.7502, -122.4337),
    "North Beach": (37.8061, -122.4103), "Oceanview/Merced/Ingleside": (37.7217, -122.4568),
    "Outer Mission": (37.7147, -122.4425), "Outer Richmond": (37.7773, -122.4942),
    "Pacific Heights": (37.7925, -122.4382), "Portola": (37.7274, -122.4077),
    "Potrero Hill": (37.7562, -122.4011), "Presidio": (37.7989, -122.4662),
    "Presidio Heights": (37.7867, -122.4530), "Russian Hill": (37.8011, -122.4198),
    "Seacliff": (37.7883, -122.4876), "South of Market": (37.7785, -122.4056),
    "Sunset/Parkside": (37.7487, -122.4942), "Tenderloin": (37.7847, -122.4141),
    "Treasure Island": (37.8235, -122.3709), "Twin Peaks": (37.7544, -122.4477),
    "Visitacion Valley": (37.7131, -122.4090), "West of Twin Peaks": (37.7423, -122.4605),
    "Western Addition": (37.7820, -122.4390),
}

SPECIAL_ALIASES = {
    "Bayview Hunters Point": ["bayview", "hunters point", "shipyard"],
    "Castro/Upper Market": ["castro", "upper market"],
    "Financial District/South Beach": ["financial district", "fidi", "south beach"],
    "Mission": ["mission district", "the mission"],
    "Oceanview/Merced/Ingleside": ["oceanview", "merced", "ingleside"],
    "South of Market": ["south of market", "soma"],
    "Sunset/Parkside": ["sunset", "parkside"],
    "Western Addition": ["western addition", "fillmore"],
}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest(snapshot: dict, lat: float, lon: float) -> tuple[dict, float]:
    candidates: list[tuple[float, dict]] = []
    for edition in snapshot.get("editions", {}).values():
        center = NEIGHBORHOOD_CENTERS.get(edition.get("name"))
        if center:
            candidates.append((_distance_miles(lat, lon, center[0], center[1]), edition))
    if not candidates:
        raise ValueError("No neighborhood centers are available")
    distance, edition = min(candidates, key=lambda item: item[0])
    return edition, round(distance, 1)


def _ring_contains(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_at_lat = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
            if lon < x_at_lat:
                inside = not inside
        j = i
    return inside


def _polygon_contains(lon: float, lat: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon or not _ring_contains(lon, lat, polygon[0]):
        return False
    return not any(_ring_contains(lon, lat, hole) for hole in polygon[1:])


def _geometry_contains(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return _polygon_contains(lon, lat, coords)
    if geometry.get("type") == "MultiPolygon":
        return any(_polygon_contains(lon, lat, polygon) for polygon in coords)
    return False


def _feature_name(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    for key in ("nhood", "analysis_neighborhood", "neighborhood", "name", "Nhood"):
        value = str(props.get(key) or "").strip()
        if value:
            return value
    return ""


class NeighborhoodLocator:
    def __init__(self) -> None:
        self.timeout = 15.0
        self._features: list[dict[str, Any]] = []
        self._loaded_at = 0.0

    async def _load(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._features and now - self._loaded_at < 24 * 3600:
            return self._features
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(DATASF_NEIGHBORHOOD_GEOJSON, params={"$limit": 100})
            response.raise_for_status()
            payload = response.json()
        features = payload.get("features") or []
        if features:
            self._features, self._loaded_at = features, now
        return self._features

    async def locate(self, snapshot: dict, lat: float, lon: float) -> tuple[dict, str, float | None]:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")
        if SF_BOUNDS["min_lat"] <= lat <= SF_BOUNDS["max_lat"] and SF_BOUNDS["min_lon"] <= lon <= SF_BOUNDS["max_lon"]:
            try:
                for feature in await self._load():
                    if _geometry_contains(lon, lat, feature.get("geometry") or {}):
                        name = _feature_name(feature)
                        edition = next((e for e in snapshot.get("editions", {}).values() if e.get("name") == name), None)
                        if edition:
                            return edition, "boundary", 0.0
            except Exception:
                pass
        edition, distance = _nearest(snapshot, lat, lon)
        return edition, "nearest", distance


def _politics(snapshot: dict, neighborhood: str) -> list[dict]:
    cards = build_quote_analysis(snapshot).get("cards", [])
    local, citywide = [], []
    for card in cards:
        title, claim = str(card.get("title") or ""), str(card.get("claim") or "")
        if title.startswith("Mayor of San Francisco"):
            citywide.append({**card, "relevance": "Citywide"})
        elif claim.startswith("d3_") and neighborhood in D3_PROXY:
            local.append({**card, "relevance": "Local district"})
        elif claim == "bayview_cleanliness" and neighborhood == "Bayview Hunters Point":
            local.append({**card, "relevance": "Local district"})
    combined = local + citywide
    combined.sort(key=lambda item: item.get("quote_date", ""), reverse=True)
    return combined[:3]


def _review_terms(neighborhood: str) -> list[str]:
    terms = [neighborhood.lower(), *SPECIAL_ALIASES.get(neighborhood, [])]
    if "/" in neighborhood:
        terms.extend(part.strip().lower() for part in neighborhood.split("/") if len(part.strip()) > 3)
    return list(dict.fromkeys(terms))


def _restaurant_review(snapshot: dict, neighborhood: str) -> dict | None:
    reviews = snapshot.get("restaurant_reviews") or []
    if not reviews:
        return None
    terms = _review_terms(neighborhood)
    scored: list[tuple[int, str, dict]] = []
    for item in reviews:
        body = _norm((item.get("title") or "") + " " + (item.get("summary") or ""))
        score = 12 if any(_norm(term) in body for term in terms) else 0
        if " review " in f" {body} ": score += 4
        publisher = _norm(item.get("publisher"))
        if any(name in publisher for name in ("san francisco chronicle", "eater", "sf standard", "infatuation", "mission local")): score += 2
        scored.append((score, str(item.get("published") or ""), item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = scored[0]
    return {**best[2], "match": f"Matches {neighborhood}" if best[0] >= 12 else "Recent San Francisco review"}


def _section_payload(edition: dict, key: str) -> dict:
    metric = edition.get("metrics", {}).get(key)
    story = next((item for item in edition.get("stories", []) if item.get("source") == key), None)
    notable = edition.get("notable", {}).get(key, [])[:3]
    if not metric or not story:
        return {"source": key, "label": SOURCE_LABELS[key], "available": False, "headline": "This feed is temporarily unavailable", "dek": "The Bulletin will retry this source during the next scheduled refresh.", "notable": []}
    return {
        "source": key, "label": SOURCE_LABELS[key], "available": True,
        "headline": story.get("headline"), "dek": story.get("dek"), "facts": story.get("facts") or [],
        "current": metric.get("current"), "baseline_week": metric.get("baseline_week"), "pct_change": metric.get("pct_change"),
        "latest": metric.get("latest"), "source_url": metric.get("source_url") or story.get("source_url"), "notable": notable,
    }


def build_happenings(snapshot: dict, edition: dict, location_mode: str, distance: float | None = None) -> dict:
    neighborhood = edition["name"]
    real_estate = (snapshot.get("real_estate") or {}).get("neighborhoods", {}).get(edition["slug"], {})
    sales = []
    for group in ("residential", "commercial"):
        if real_estate.get(group): sales.append(real_estate[group][0])
    editorial = edition.get("editorial") or {}
    return {
        "generated_at": snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "location_mode": location_mode,
        "neighborhood": {"name": neighborhood, "slug": edition["slug"]},
        "distance_miles": distance,
        "outside_sf": bool(distance is not None and distance > 12),
        "sections": [_section_payload(edition, key) for key in SOURCE_ORDER],
        "politics": _politics(snapshot, neighborhood),
        "real_estate": sales,
        "coverage": (editorial.get("coverage") or [])[:3],
        "restaurant_review": _restaurant_review(snapshot, neighborhood),
    }
