from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


MAX_PINS = 8


def _text(value: Any, limit: int = 180) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip(" ,;:-") + "…"


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _valid_sf(lat: float, lon: float) -> bool:
    return 37.60 <= lat <= 37.86 and -122.56 <= lon <= -122.32


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    coords = value.get("coordinates")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lon, lat = float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            pass
        else:
            if _valid_sf(lat, lon):
                return lat, lon
    lat_value = value.get("latitude") if value.get("latitude") is not None else value.get("lat")
    lon_value = value.get("longitude") if value.get("longitude") is not None else value.get("lon")
    if lon_value is None:
        lon_value = value.get("long")
    try:
        lat, lon = float(lat_value), float(lon_value)
    except (TypeError, ValueError):
        return None
    return (lat, lon) if _valid_sf(lat, lon) else None


def _lat_lon(lat_value: Any, lon_value: Any) -> tuple[float, float] | None:
    try:
        lat, lon = float(lat_value), float(lon_value)
    except (TypeError, ValueError):
        return None
    return (lat, lon) if _valid_sf(lat, lon) else None


def _money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}" if amount else ""


def _owner(item: dict) -> str:
    for key in ("owner_name", "permit_owner", "owner"):
        value = _text(item.get(key), 100)
        if value:
            return value
    owners = item.get("owners") or []
    if isinstance(owners, list) and owners:
        first = owners[0]
        if isinstance(first, dict):
            return _text(first.get("name") or first.get("firm_name"), 100)
        return _text(first, 100)
    return ""


def _contractor(item: dict) -> str:
    for key in ("general_contractor", "contractor_name", "contractor"):
        value = _text(item.get(key), 100)
        if value:
            return value
    contractors = item.get("contractors") or []
    if isinstance(contractors, list) and contractors:
        first = contractors[0]
        if isinstance(first, dict):
            return _text(first.get("name") or first.get("firm_name"), 100)
        return _text(first, 100)
    return ""


def _raw_indexes(raw_sources: list[dict]) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, tuple[float, float]],
    dict[str, tuple[float, float]],
    dict[str, tuple[float, float]],
    dict[str, Any],
]:
    permits: dict[str, tuple[float, float]] = {}
    businesses: dict[str, tuple[float, float]] = {}
    services: dict[str, tuple[float, float]] = {}
    police: dict[str, tuple[float, float]] = {}
    boundaries: dict[str, Any] = {}

    for source in raw_sources:
        if source.get("map_boundaries"):
            boundaries.update(source.get("map_boundaries") or {})
        key = source.get("key")
        for row in source.get("recent") or []:
            if key == "permits":
                coords = _point(row.get("_map_point"))
                permit_number = _text(row.get("permit_number"), 40)
                if coords and permit_number:
                    permits.setdefault(permit_number, coords)
            elif key == "businesses":
                coords = _point(row.get("location"))
                address = _norm(row.get("full_business_address"))
                if coords and address:
                    businesses.setdefault(address, coords)
            elif key == "service_requests":
                coords = _lat_lon(row.get("lat"), row.get("long")) or _point(row.get("point"))
                address = _norm(row.get("address"))
                if coords and address:
                    services.setdefault(address, coords)
            elif key == "police":
                coords = _point(row.get("point")) or _lat_lon(row.get("latitude"), row.get("longitude"))
                incident = _text(row.get("incident_number"), 40)
                if coords and incident:
                    police.setdefault(incident, coords)
    return permits, businesses, services, police, boundaries


def _permit_pin(item: dict, coords: tuple[float, float], slug: str) -> dict:
    unit_delta = int(item.get("unit_delta") or 0)
    value = _money(item.get("cost"))
    detail_parts = []
    if unit_delta:
        detail_parts.append(f"{unit_delta:+d} proposed housing unit{'s' if abs(unit_delta) != 1 else ''}")
    if value:
        detail_parts.append(f"{value} listed project value")
    owner = _owner(item)
    contractor = _contractor(item)
    if owner:
        detail_parts.append(f"Owner: {owner}")
    if contractor:
        detail_parts.append(f"GC: {contractor}")
    score = 100 + max(unit_delta, 0) * 8 + (math.log10(float(item.get("cost") or 1)) * 2 if item.get("cost") else 0)
    return {
        "category": "permits",
        "label": "Development",
        "title": _text(item.get("address") or item.get("title") or "Building permit", 110),
        "detail": _text(" · ".join(detail_parts) or item.get("scope_summary") or item.get("description"), 220),
        "address": _text(item.get("address"), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": f"/neighborhood/{slug}#story-permits",
        "score": round(score, 1),
    }


def _business_pin(item: dict, coords: tuple[float, float], slug: str) -> dict:
    owner = _text(item.get("owner"), 100)
    return {
        "category": "businesses",
        "label": "Business",
        "title": _text(item.get("title") or "Business registration", 110),
        "detail": _text(f"New location registration{f' · Owner: {owner}' if owner else ''}", 180),
        "address": _text(item.get("address"), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": f"/neighborhood/{slug}#story-businesses",
        "score": 78,
    }


def _service_pin(item: dict, coords: tuple[float, float], slug: str) -> dict:
    return {
        "category": "service_requests",
        "label": "City service",
        "title": _text(item.get("title") or item.get("category") or "311 request", 110),
        "detail": _text(item.get("description") or item.get("status") or "Recent 311 request", 180),
        "address": _text(item.get("address"), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": f"/neighborhood/{slug}#story-service_requests",
        "score": 45,
    }


def _police_pin(item: dict, coords: tuple[float, float], slug: str) -> dict:
    reported = _text(item.get("reported_display"), 80)
    return {
        "category": "police",
        "label": "Public safety",
        "title": _text(item.get("title") or "Police report filed", 110),
        "detail": _text(f"{f'Reported {reported}' if reported else 'Recent SFPD filing'} · privacy-protected intersection", 180),
        "address": _text(item.get("address"), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": f"/neighborhood/{slug}#story-police",
        "score": 62,
    }


def build_map_activity(snapshot: dict, raw_sources: list[dict], generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
    permit_points, business_points, service_points, police_points, boundaries = _raw_indexes(raw_sources)

    for slug, edition in (snapshot.get("editions") or {}).items():
        candidates: list[dict] = []
        notable = edition.get("notable") or {}

        for item in (notable.get("permits") or [])[:4]:
            coords = permit_points.get(_text(item.get("permit_number"), 40))
            if coords:
                candidates.append(_permit_pin(item, coords, slug))

        for item in (notable.get("businesses") or [])[:3]:
            coords = business_points.get(_norm(item.get("address")))
            if coords:
                candidates.append(_business_pin(item, coords, slug))

        for item in (notable.get("police") or [])[:3]:
            coords = police_points.get(_text(item.get("incident_number"), 40))
            if coords:
                candidates.append(_police_pin(item, coords, slug))

        for item in (notable.get("service_requests") or [])[:3]:
            coords = service_points.get(_norm(item.get("address")))
            if coords:
                candidates.append(_service_pin(item, coords, slug))

        candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        selected: list[dict] = []
        category_counts: dict[str, int] = {}
        seen_coords: set[tuple[float, float, str]] = set()
        per_category_limit = {"permits": 3, "businesses": 2, "police": 2, "service_requests": 2}
        for item in candidates:
            category = item.get("category") or "other"
            key = (round(float(item["lat"]), 5), round(float(item["lon"]), 5), category)
            if key in seen_coords or category_counts.get(category, 0) >= per_category_limit.get(category, 2):
                continue
            selected.append({k: v for k, v in item.items() if k != "score"})
            seen_coords.add(key)
            category_counts[category] = category_counts.get(category, 0) + 1
            if len(selected) >= MAX_PINS:
                break

        edition["map_activity"] = {
            "updated_at": generated_at.isoformat(),
            "pins": selected,
            "pin_count": len(selected),
            "counts": category_counts,
            "boundary": boundaries.get(edition.get("name") or ""),
            "source_note": (
                "Pins are selected highlights from the current Bulletin edition. Permit addresses are matched to the City's Enterprise Addressing System; "
                "business and 311 locations use source-published coordinates; SFPD locations are the privacy-protected nearby intersections published by SFPD."
            ),
        }

    snapshot["map_activity_updated_at"] = generated_at.isoformat()
    return snapshot
