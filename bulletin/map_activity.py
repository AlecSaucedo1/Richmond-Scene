from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


MAX_PINS = 22
HIGHLIGHT_COUNT = 8
ADDRESS_DATASET_ID = "5mjj-njit"

VENUE_ADDRESSES = {
    "SFMOMA": "151 3rd St",
    "de Young": "50 Hagiwara Tea Garden Dr",
    "Legion of Honor": "100 34th Ave",
    "Asian Art Museum": "200 Larkin St",
    "Museum of the African Diaspora": "685 Mission St",
    "Yerba Buena Center for the Arts": "701 Mission St",
    "SFJAZZ Center": "201 Franklin St",
    "Davies Symphony Hall": "201 Van Ness Ave",
    "War Memorial Opera House": "301 Van Ness Ave",
    "The Fillmore": "1805 Geary Blvd",
    "Great American Music Hall": "859 O'Farrell St",
    "The Independent": "628 Divisadero St",
    "Chase Center": "1 Warriors Way",
    "Palace of Fine Arts": "3601 Lyon St",
}


def _text(value: Any, limit: int = 180) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip(" ,;:-") + "…"


def _norm(value: Any) -> str:
    clean = str(value or "").upper()
    replacements = {
        " STREET": " ST",
        " AVENUE": " AVE",
        " BOULEVARD": " BLVD",
        " ROAD": " RD",
        " DRIVE": " DR",
        " LANE": " LN",
        " PLACE": " PL",
        " TERRACE": " TER",
        " COURT": " CT",
        " THIRD ": " 3RD ",
        " SECOND ": " 2ND ",
        " FIRST ": " 1ST ",
    }
    for old, new in replacements.items():
        clean = clean.replace(old, new)
    return re.sub(r"[^A-Z0-9]+", " ", clean).strip()


def _base_address(value: Any) -> str:
    raw = _text(value, 160).split(",", 1)[0]
    raw = re.sub(r"\s+(?:APT|UNIT|STE|SUITE|#)\s*[^,]+$", "", raw, flags=re.I)
    return raw.strip()


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
        "detail": _text(" · ".join(detail_parts) or item.get("scope_summary") or item.get("description"), 240),
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
        "detail": _text(f"New location registration{f' · Owner: {owner}' if owner else ''}", 200),
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
        "detail": _text(item.get("description") or item.get("status") or "Recent 311 request", 200),
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
        "detail": _text(f"{f'Reported {reported}' if reported else 'Recent SFPD filing'} · privacy-protected intersection", 200),
        "address": _text(item.get("address"), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": f"/neighborhood/{slug}#story-police",
        "score": 62,
    }


def _select_core(candidates: list[dict]) -> tuple[list[dict], dict[str, int]]:
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    selected: list[dict] = []
    category_counts: dict[str, int] = {}
    seen_coords: set[tuple[float, float, str]] = set()
    per_category_limit = {"permits": 6, "businesses": 5, "police": 5, "service_requests": 5}
    for item in candidates:
        category = item.get("category") or "other"
        key = (round(float(item["lat"]), 5), round(float(item["lon"]), 5), category)
        if key in seen_coords or category_counts.get(category, 0) >= per_category_limit.get(category, 4):
            continue
        clean = {k: v for k, v in item.items() if k != "score"}
        clean["highlight"] = len(selected) < HIGHLIGHT_COUNT
        selected.append(clean)
        seen_coords.add(key)
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(selected) >= MAX_PINS:
            break
    return selected, category_counts


def build_map_activity(snapshot: dict, raw_sources: list[dict], generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
    permit_points, business_points, service_points, police_points, boundaries = _raw_indexes(raw_sources)

    for slug, edition in (snapshot.get("editions") or {}).items():
        candidates: list[dict] = []
        notable = edition.get("notable") or {}

        for item in (notable.get("permits") or [])[:6]:
            coords = permit_points.get(_text(item.get("permit_number"), 40))
            if coords:
                candidates.append(_permit_pin(item, coords, slug))

        for item in (notable.get("businesses") or [])[:8]:
            coords = business_points.get(_norm(item.get("address")))
            if coords:
                candidates.append(_business_pin(item, coords, slug))

        for item in (notable.get("police") or [])[:8]:
            coords = police_points.get(_text(item.get("incident_number"), 40))
            if coords:
                candidates.append(_police_pin(item, coords, slug))

        for item in (notable.get("service_requests") or [])[:8]:
            coords = service_points.get(_norm(item.get("address")))
            if coords:
                candidates.append(_service_pin(item, coords, slug))

        selected, category_counts = _select_core(candidates)
        edition["map_activity"] = {
            "updated_at": generated_at.isoformat(),
            "pins": selected,
            "pin_count": len(selected),
            "highlight_count": sum(1 for item in selected if item.get("highlight")),
            "counts": category_counts,
            "boundary": boundaries.get(edition.get("name") or ""),
            "source_note": (
                "The default view shows the highest-signal mapped records; All signals expands the current seven-day map layer. "
                "Permit addresses are matched to the City's Enterprise Addressing System; business and 311 locations use source-published coordinates; "
                "SFPD locations are the privacy-protected nearby intersections published by SFPD."
            ),
        }

    snapshot["map_activity_updated_at"] = generated_at.isoformat()
    return snapshot


async def _resolve_addresses(datasf, addresses: list[str]) -> dict[str, tuple[float, float]]:
    requested = list(dict.fromkeys(_base_address(value) for value in addresses if _base_address(value)))
    matches: dict[str, tuple[float, float]] = {}
    for start in range(0, len(requested), 30):
        chunk = requested[start : start + 30]
        clauses = [f"upper(address) like '{value.upper().replace(chr(39), chr(39) * 2)}%'" for value in chunk]
        try:
            rows = await datasf._get(
                ADDRESS_DATASET_ID,
                {"$select": "address,point", "$where": " OR ".join(clauses), "$limit": "3000"},
            )
        except Exception as exc:
            print(f"Context map address resolution failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        for row in rows:
            coords = _point(row.get("point"))
            row_norm = _norm(row.get("address"))
            if not coords or not row_norm:
                continue
            for value in chunk:
                request_norm = _norm(value)
                if request_norm and (row_norm.startswith(request_norm) or request_norm.startswith(row_norm)):
                    matches.setdefault(request_norm, coords)
    return matches


def _real_estate_pin(item: dict, coords: tuple[float, float]) -> dict:
    price = _money(item.get("sale_price"))
    kind = _text(item.get("property_type") or item.get("property_group") or "Property", 60)
    sale_date = _text(item.get("sale_date") or item.get("recorded_date"), 30)
    detail = " · ".join(part for part in (f"{price} transaction" if price else "Property transaction", kind, sale_date) if part)
    return {
        "category": "real_estate",
        "label": "Real estate",
        "title": _text(item.get("address") or "Property transaction", 110),
        "detail": _text(detail, 200),
        "address": _text(item.get("address"), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": "/real-estate",
        "highlight": False,
    }


def _arts_pin(item: dict, coords: tuple[float, float]) -> dict:
    venue = _text(item.get("museum") or item.get("venue"), 90)
    date_label = _text(item.get("start_date"), 30)
    detail = " · ".join(part for part in (venue, item.get("status"), date_label) if part)
    return {
        "category": "arts",
        "label": "Arts & culture",
        "title": _text(item.get("title") or venue or "Arts program", 120),
        "detail": _text(detail, 200),
        "address": _text(item.get("address") or VENUE_ADDRESSES.get(venue), 130),
        "lat": coords[0],
        "lon": coords[1],
        "href": "/arts",
        "highlight": False,
    }


async def enrich_context_signals(snapshot: dict, datasf, generated_at: datetime | None = None) -> dict:
    """Add mapped real-estate and arts signals after those desks finish refreshing."""
    generated_at = generated_at or datetime.now(timezone.utc)
    real_estate = snapshot.get("real_estate") or {}
    arts = snapshot.get("arts") or {}
    addresses: list[str] = []

    for edition in (snapshot.get("editions") or {}).values():
        slug = edition.get("slug") or ""
        real = (real_estate.get("neighborhoods") or {}).get(slug) or {}
        for item in (real.get("residential") or [])[:2] + (real.get("commercial") or [])[:2]:
            if item.get("address"):
                addresses.append(item["address"])
        art = (arts.get("neighborhoods") or {}).get(edition.get("name") or "") or {}
        for item in (art.get("exhibitions") or [])[:2] + (art.get("events") or [])[:2]:
            venue = _text(item.get("museum") or item.get("venue"), 90)
            address = item.get("address") or VENUE_ADDRESSES.get(venue)
            if address:
                addresses.append(address)

    if not addresses:
        return snapshot
    points = await _resolve_addresses(datasf, addresses)

    for edition in (snapshot.get("editions") or {}).values():
        activity = edition.get("map_activity") or {}
        pins = list(activity.get("pins") or [])
        existing = {(round(float(pin.get("lat") or 0), 5), round(float(pin.get("lon") or 0), 5), pin.get("category")) for pin in pins}
        slug = edition.get("slug") or ""

        real = (real_estate.get("neighborhoods") or {}).get(slug) or {}
        for item in (real.get("residential") or [])[:2] + (real.get("commercial") or [])[:2]:
            coords = points.get(_norm(_base_address(item.get("address"))))
            if not coords:
                continue
            key = (round(coords[0], 5), round(coords[1], 5), "real_estate")
            if key not in existing:
                pins.append(_real_estate_pin(item, coords))
                existing.add(key)

        art = (arts.get("neighborhoods") or {}).get(edition.get("name") or "") or {}
        for item in (art.get("exhibitions") or [])[:2] + (art.get("events") or [])[:2]:
            venue = _text(item.get("museum") or item.get("venue"), 90)
            address = item.get("address") or VENUE_ADDRESSES.get(venue)
            coords = points.get(_norm(_base_address(address))) if address else None
            if not coords:
                continue
            key = (round(coords[0], 5), round(coords[1], 5), "arts")
            if key not in existing:
                pins.append(_arts_pin(item, coords))
                existing.add(key)

        pins = pins[:MAX_PINS]
        counts: dict[str, int] = {}
        for pin in pins:
            category = str(pin.get("category") or "other")
            counts[category] = counts.get(category, 0) + 1
        activity["pins"] = pins
        activity["pin_count"] = len(pins)
        activity["highlight_count"] = sum(1 for pin in pins if pin.get("highlight"))
        activity["counts"] = counts
        activity["updated_at"] = generated_at.isoformat()
        edition["map_activity"] = activity

    snapshot["map_activity_updated_at"] = generated_at.isoformat()
    return snapshot
