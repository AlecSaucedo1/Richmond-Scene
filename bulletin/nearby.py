from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .political_quotes import D3_PROXY, build_quote_analysis

SOURCE_ORDER = ("businesses", "permits", "service_requests", "police")
SOURCE_LABELS = {
    "businesses": "Business & storefronts",
    "permits": "Development & housing",
    "service_requests": "Streets & city services",
    "police": "Public safety",
}

NEIGHBORHOOD_CENTERS: dict[str, tuple[float, float]] = {
    "Bayview Hunters Point": (37.7304, -122.3844),
    "Bernal Heights": (37.7412, -122.4146),
    "Castro/Upper Market": (37.7609, -122.4350),
    "Chinatown": (37.7941, -122.4078),
    "Excelsior": (37.7212, -122.4323),
    "Financial District/South Beach": (37.7900, -122.3970),
    "Glen Park": (37.7330, -122.4332),
    "Golden Gate Park": (37.7694, -122.4862),
    "Haight Ashbury": (37.7692, -122.4481),
    "Hayes Valley": (37.7764, -122.4242),
    "Inner Richmond": (37.7804, -122.4660),
    "Inner Sunset": (37.7615, -122.4664),
    "Japantown": (37.7854, -122.4294),
    "Lakeshore": (37.7305, -122.4935),
    "Lincoln Park": (37.7842, -122.4949),
    "Lone Mountain/USF": (37.7795, -122.4519),
    "Marina": (37.8030, -122.4360),
    "McLaren Park": (37.7194, -122.4194),
    "Mission": (37.7599, -122.4148),
    "Mission Bay": (37.7716, -122.3875),
    "Nob Hill": (37.7930, -122.4161),
    "Noe Valley": (37.7502, -122.4337),
    "North Beach": (37.8061, -122.4103),
    "Oceanview/Merced/Ingleside": (37.7217, -122.4568),
    "Outer Mission": (37.7147, -122.4425),
    "Outer Richmond": (37.7773, -122.4942),
    "Pacific Heights": (37.7925, -122.4382),
    "Portola": (37.7274, -122.4077),
    "Potrero Hill": (37.7562, -122.4011),
    "Presidio": (37.7989, -122.4662),
    "Presidio Heights": (37.7867, -122.4530),
    "Russian Hill": (37.8011, -122.4198),
    "Seacliff": (37.7883, -122.4876),
    "South of Market": (37.7785, -122.4056),
    "Sunset/Parkside": (37.7487, -122.4942),
    "Tenderloin": (37.7847, -122.4141),
    "Treasure Island": (37.8235, -122.3709),
    "Twin Peaks": (37.7544, -122.4477),
    "Visitacion Valley": (37.7131, -122.4090),
    "West of Twin Peaks": (37.7423, -122.4605),
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
        if not center:
            continue
        candidates.append((_distance_miles(lat, lon, center[0], center[1]), edition))
    if not candidates:
        raise ValueError("No neighborhood centers are available")
    distance, edition = min(candidates, key=lambda item: item[0])
    return edition, round(distance, 1)


def _politics(snapshot: dict, neighborhood: str) -> list[dict]:
    cards = build_quote_analysis(snapshot).get("cards", [])
    local: list[dict] = []
    citywide: list[dict] = []
    for card in cards:
        title = str(card.get("title") or "")
        claim = str(card.get("claim") or "")
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
        score = 0
        if any(_norm(term) in body for term in terms):
            score += 12
        if " review " in f" {body} ":
            score += 4
        publisher = _norm(item.get("publisher"))
        if any(name in publisher for name in ("san francisco chronicle", "eater", "sf standard", "kqed")):
            score += 2
        scored.append((score, str(item.get("published") or ""), item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = scored[0][2]
    return {
        **best,
        "match": f"Matches {neighborhood}" if scored[0][0] >= 12 else "Recent San Francisco review",
    }


def _section_payload(edition: dict, key: str) -> dict:
    metric = edition.get("metrics", {}).get(key)
    story = next((item for item in edition.get("stories", []) if item.get("source") == key), None)
    notable = edition.get("notable", {}).get(key, [])[:3]
    if not metric or not story:
        return {
            "source": key,
            "label": SOURCE_LABELS[key],
            "available": False,
            "headline": "This feed is temporarily unavailable",
            "dek": "The Bulletin will retry this source during the next scheduled refresh.",
            "notable": [],
        }
    return {
        "source": key,
        "label": SOURCE_LABELS[key],
        "available": True,
        "headline": story.get("headline"),
        "dek": story.get("dek"),
        "current": metric.get("current"),
        "baseline_week": metric.get("baseline_week"),
        "pct_change": metric.get("pct_change"),
        "latest": metric.get("latest"),
        "source_url": metric.get("source_url") or story.get("source_url"),
        "notable": notable,
    }


def build_happenings(
    snapshot: dict,
    *,
    lat: float | None = None,
    lon: float | None = None,
    slug: str | None = None,
) -> dict:
    distance: float | None = None
    mode = "selected"
    if slug:
        edition = snapshot.get("editions", {}).get(slug)
        if not edition:
            raise ValueError("Neighborhood not found")
    else:
        if lat is None or lon is None:
            raise ValueError("Latitude and longitude are required")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")
        edition, distance = _nearest(snapshot, lat, lon)
        mode = "nearest"

    neighborhood = edition["name"]
    generated = snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": generated,
        "location_mode": mode,
        "neighborhood": {"name": neighborhood, "slug": edition["slug"]},
        "distance_miles": distance,
        "outside_sf": bool(distance is not None and distance > 12),
        "sections": [_section_payload(edition, key) for key in SOURCE_ORDER],
        "politics": _politics(snapshot, neighborhood),
        "restaurant_review": _restaurant_review(snapshot, neighborhood),
    }
