from __future__ import annotations

import re
from collections import Counter
from typing import Any

from . import analysis as base
from .config import SOURCES, SourceConfig

_ORIGINAL_BUILD_SNAPSHOT = base.build_snapshot


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _lower(value: Any) -> str:
    return _norm(value).lower()


def _sentence(value: Any) -> str:
    raw = _norm(value)
    if not raw:
        return ""
    raw = re.sub(r"\bOTC\b", "over-the-counter", raw, flags=re.I)
    raw = re.sub(r"\bMUNI\b", "Muni", raw, flags=re.I)
    return raw[0].upper() + raw[1:]


def readable_permit_type(value: Any) -> str:
    raw = _lower(value)
    if not raw:
        return "Building permit"
    if "otc" in raw and ("alter" in raw or "repair" in raw):
        return "Minor alterations & repairs"
    if "alter" in raw and "repair" in raw:
        return "Alterations & repairs"
    if "new construction" in raw or "new building" in raw:
        return "New construction"
    if "demol" in raw:
        return "Demolition"
    if "grading" in raw or "shoring" in raw:
        return "Grading & shoring"
    if "sign" in raw:
        return "Sign work"
    if "additions" in raw and "alter" in raw:
        return "Addition or alteration"
    cleaned = re.sub(r"\bpermit\b", "", _norm(value), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -/")
    return _sentence(cleaned or "Building permit")


def readable_service_category(value: Any) -> str:
    raw = _lower(value)
    if "graffiti" in raw:
        return "graffiti reports"
    if "abandoned vehicle" in raw:
        return "abandoned-vehicle reports"
    if "blocked street" in raw or "blocked sidewalk" in raw:
        return "blocked street or sidewalk reports"
    if "street and sidewalk cleaning" in raw:
        return "street and sidewalk cleaning"
    if "encamp" in raw:
        return "encampment-related requests"
    if "noise" in raw:
        return "noise complaints"
    if "tree" in raw:
        return "tree-maintenance requests"
    if "streetlight" in raw:
        return "streetlight requests"
    if "general request" in raw and "public works" in raw:
        return "Public Works requests"
    if "muni" in raw:
        return "Muni feedback"
    return base.label(value, "service_requests")


def readable_service_title(service_name: Any, subtype: Any, details: Any) -> str:
    service = _lower(service_name)
    sub = _lower(subtype)
    detail = _lower(details)
    blob = " ".join(x for x in (service, sub, detail) if x)

    if "graffiti" in blob:
        if "public" in sub or "public" in detail:
            return "Graffiti reported on public property"
        if "private" in sub or "private" in detail:
            return "Graffiti reported on private property"
        return "Graffiti reported"
    if "abandoned vehicle" in blob:
        return "Abandoned vehicle reported"
    if "blocked street" in blob or "blocked sidewalk" in blob or "blocked street or sidewalk" in blob:
        return "Blocked street or sidewalk reported"
    if "encamp" in blob:
        return "Encampment-related service request"
    if "noise" in blob:
        return "Noise complaint"
    if "streetlight" in blob:
        return "Streetlight issue reported"
    if "street and sidewalk cleaning" in blob:
        return "Street or sidewalk cleaning request"
    if "tree" in service:
        useful = _norm(subtype)
        if useful and _lower(useful) not in {service, "tree maintenance"}:
            return f"Tree maintenance: {_sentence(useful)}"
        return "Tree-maintenance request"
    if "muni" in service:
        useful = _norm(subtype)
        return f"Muni feedback: {_sentence(useful)}" if useful and _lower(useful) != service else "Muni service feedback"

    useful = _norm(subtype)
    category = _norm(service_name)
    if useful and _lower(useful) != service:
        cleaned = re.sub(r"[_-]+", " ", useful)
        return _sentence(cleaned if cleaned.lower().endswith(("request", "report", "complaint")) else cleaned + " request")
    return _sentence((category or "311 service") + ("" if category.lower().endswith(("request", "report")) else " request"))


POLICE_CATEGORY = {
    "larceny theft": "Theft",
    "motor vehicle theft": "Vehicle theft",
    "malicious mischief": "Vandalism",
    "assault": "Assault",
    "burglary": "Burglary",
    "robbery": "Robbery",
    "fraud": "Fraud",
    "drug offense": "Drug offenses",
    "weapons offense": "Weapons offenses",
    "missing person": "Missing-person reports",
    "warrant": "Warrant-related incidents",
    "non-criminal": "Non-criminal incidents",
    "disorderly conduct": "Disorderly-conduct reports",
    "suspicious occurrence": "Suspicious-occurrence reports",
}


def readable_police_category(value: Any) -> str:
    raw = _lower(value)
    return POLICE_CATEGORY.get(raw, _sentence(value or "Reported incidents"))


def readable_police_title(category: Any, subcategory: Any, description: Any) -> str:
    blob = " ".join(_lower(x) for x in (category, subcategory, description) if _norm(x))
    if "from vehicle" in blob or "theft, from locked vehicle" in blob or "theft, from unlocked vehicle" in blob:
        return "Theft from a vehicle reported"
    if "motor vehicle theft" in blob or "vehicle, stolen" in blob or "stolen vehicle" in blob:
        return "Vehicle theft reported"
    if "burglary" in blob:
        return "Burglary reported"
    if "robbery" in blob:
        return "Robbery reported"
    if "assault" in blob:
        return "Assault reported"
    if "malicious mischief" in blob or "vandalism" in blob:
        return "Vandalism reported"
    if "fraud" in blob:
        return "Fraud report"
    if "missing person" in blob:
        return "Missing-person report"
    if "drug" in blob:
        return "Drug-related incident reported"
    if "weapon" in blob:
        return "Weapons-related incident reported"
    if "suspicious" in blob:
        return "Suspicious occurrence reported"
    name = readable_police_category(category)
    if name.lower().endswith(("reports", "incidents")):
        return name
    return f"{name} reported"


def readable_category(value: Any, source: str) -> str:
    if source == "permits":
        return readable_permit_type(value)
    if source == "service_requests":
        return readable_service_category(value)
    if source == "police":
        return readable_police_category(value)
    return base.label(value, source)


def _permit_records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for r in rows:
        if _norm(r.get(cfg.neighborhood_field)) != hood:
            continue
        existing_units = base.unit_count(r.get("existing_units"))
        proposed_units = base.unit_count(r.get("proposed_units"))
        unit_delta = proposed_units - existing_units if existing_units is not None and proposed_units is not None else None
        raw_type = base.text(r.get("permit_type_definition") or "Building permit", 100)
        scope = base.text(r.get("description"), 240)
        existing_use = base.text(r.get("existing_use"), 90)
        proposed_use = base.text(r.get("proposed_use"), 90)
        context: list[str] = []
        if scope:
            context.append(scope)
        if proposed_use and proposed_use != existing_use:
            context.append(f"Use: {existing_use or 'not listed'} → {proposed_use}")
        prepared.append({
            "title": readable_permit_type(raw_type),
            "raw_title": raw_type,
            "address": " ".join(str(r.get(k) or "").strip() for k in ("street_number", "street_name", "street_suffix")).strip(),
            "description": base.text(" · ".join(context), 300),
            "cost": base.num(r.get("estimated_cost")),
            "status": base.text(r.get("status"), 60),
            "permit_number": base.text(r.get("permit_number"), 40),
            "existing_units": existing_units,
            "proposed_units": proposed_units,
            "unit_delta": unit_delta,
            "existing_use": existing_use,
            "proposed_use": proposed_use,
        })
    prepared.sort(key=lambda x: (max(x.get("unit_delta") or 0, 0), x.get("cost") or 0), reverse=True)
    return prepared[:8]


def _service_records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if _norm(r.get(cfg.neighborhood_field)) != hood:
            continue
        service = _norm(r.get("service_name"))
        subtype = _norm(r.get("service_subtype"))
        details = _norm(r.get("service_details"))
        address = base.text(r.get("address"), 120)
        title = readable_service_title(service, subtype, details)
        key = (title.lower(), address.lower())
        if key in seen:
            continue
        seen.add(key)
        context: list[str] = []
        if details and _lower(details) not in {_lower(title), _lower(service), _lower(subtype)}:
            context.append(_sentence(details))
        if subtype and _lower(subtype) not in {_lower(title), _lower(service)} and not _lower(subtype).startswith("graffiti public") and not _lower(subtype).startswith("graffiti private"):
            context.append(f"Request type: {_sentence(subtype)}")
        out.append({
            "title": title,
            "raw_title": subtype or service,
            "category": readable_service_category(service),
            "address": address,
            "description": base.text(" · ".join(dict.fromkeys(context)), 220),
            "status": base.text(r.get("status_description"), 40),
        })
        if len(out) == 8:
            break
    return out


def _police_records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    grouped: Counter[tuple[str, str, str, str, str]] = Counter()
    for r in rows:
        if _norm(r.get(cfg.neighborhood_field)) != hood:
            continue
        category = base.text(r.get("incident_category"), 100)
        subcategory = base.text(r.get("incident_subcategory"), 120)
        description = base.text(r.get("incident_description"), 160)
        intersection = base.text(r.get("intersection"), 120)
        resolution = base.text(r.get("resolution"), 80)
        title = readable_police_title(category, subcategory, description)
        grouped[(title, readable_police_category(category), description or subcategory, intersection, resolution)] += 1
    records: list[dict[str, Any]] = []
    for (title, category, description, intersection, resolution), count in grouped.most_common(8):
        records.append({
            "title": title,
            "category": category,
            "description": description if _lower(description) not in {_lower(title), _lower(category)} else "",
            "address": intersection,
            "status": resolution,
            "count": count,
        })
    return records


def readable_records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    if cfg.key == "permits":
        return _permit_records(cfg, rows, hood)
    if cfg.key == "service_requests":
        return _service_records(cfg, rows, hood)
    if cfg.key == "police":
        return _police_records(cfg, rows, hood)
    return base.records(cfg, rows, hood)


def build_snapshot(raw_sources: list[dict[str, Any]], generated_at) -> dict[str, Any]:
    snapshot = _ORIGINAL_BUILD_SNAPSHOT(raw_sources, generated_at)
    raw = {item.get("key"): item for item in raw_sources}

    for edition in snapshot.get("editions", {}).values():
        hood = edition.get("name", "")
        rebuilt_stories: list[dict[str, Any]] = []
        for cfg in SOURCES:
            metric = edition.get("metrics", {}).get(cfg.key)
            source = raw.get(cfg.key)
            if not metric or not source:
                continue

            categories = metric.get("categories") or []
            for category in categories:
                category["display_category"] = readable_category(category.get("category"), cfg.key)

            recs = readable_records(cfg, source.get("recent", []), hood)
            edition.setdefault("notable", {})[cfg.key] = recs
            rebuilt_stories.append(base.story(cfg, hood, metric, categories, recs))

        rebuilt_stories.sort(key=lambda item: item.get("interest", 0), reverse=True)
        edition["stories"] = rebuilt_stories
        edition["lead"] = rebuilt_stories[0] if rebuilt_stories else None
        edition["quick_read"] = base.quick_read(edition)

    snapshot["front_page"] = base.front_page(snapshot.get("editions", {}))
    methodology = snapshot.setdefault("methodology", {})
    methodology["readability"] = (
        "Raw DataSF permit types, 311 subtypes and police classifications are translated into plain-English display labels. "
        "Addresses, scope descriptions, use changes, service details, incident descriptions and source-published intersections/resolutions are retained when useful for context."
    )
    return snapshot
