from __future__ import annotations

import re
from datetime import datetime
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


def _money(value: Any) -> str:
    amount = base.num(value)
    if amount <= 0:
        return ""
    return base.money(amount)


def _date_label(value: Any, include_time: bool = False) -> str:
    raw = _norm(value)
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if include_time:
            clock = parsed.strftime("%I:%M %p").lstrip("0")
            return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} · {clock}"
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
    except (TypeError, ValueError):
        return raw[:16].replace("T", " · ")


# DBI scope-of-work descriptions are useful but often written in plan-review shorthand.
# These substitutions expand only common construction abbreviations without adding facts.
PERMIT_SCOPE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\(e\)", "existing"),
    (r"\(n\)", "new"),
    (r"\bw/o\b", "without"),
    (r"\bw/", "with "),
    (r"\br\s*&\s*r\b", "remove and replace"),
    (r"\br\s*/\s*r\b", "remove and replace"),
    (r"\brepl\.?\b", "replace"),
    (r"\breplc\.?\b", "replace"),
    (r"\binstl?\.?\b", "install"),
    (r"\bext\.?\b", "exterior"),
    (r"\bint\.?\b", "interior"),
    (r"\bbldg\.?\b", "building"),
    (r"\bkitch\.?\b", "kitchen"),
    (r"\bbthr?m\.?\b", "bathroom"),
    (r"\bflr\.?\b", "floor"),
    (r"\bwdw?s?\.?\b", "window"),
    (r"\bmech\.?\b", "mechanical"),
    (r"\belec\.?\b", "electrical"),
    (r"\bplumb\.?\b", "plumbing"),
    (r"\bstruct\.?\b", "structural"),
    (r"\bT\.?I\.?\b", "tenant improvements"),
    (r"\bMEP\b", "mechanical, electrical and plumbing"),
    (r"\bADA\b", "ADA accessibility"),
    (r"\bADU\b", "accessory dwelling unit (ADU)"),
    (r"\bN/?A\b", ""),
)


def readable_permit_scope(value: Any) -> str:
    raw = _norm(value)
    if not raw:
        return "Scope of work was not described in the public filing."

    cleaned = raw.replace("&", " and ").replace("@", " at ")
    cleaned = re.sub(r"\s*;\s*", ". ", cleaned)
    cleaned = re.sub(r"\s*\|\s*", ". ", cleaned)
    for pattern, replacement in PERMIT_SCOPE_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)

    # DBI descriptions are frequently entered in all caps. Sentence case makes them
    # readable while leaving numbers, addresses and technical acronyms intact.
    letters = [c for c in cleaned if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.78:
        cleaned = cleaned.lower()
        cleaned = re.sub(r"\bada\b", "ADA", cleaned)
        cleaned = re.sub(r"\badu\b", "ADU", cleaned)
        cleaned = re.sub(r"\bhvac\b", "HVAC", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"([.]){2,}", ".", cleaned)
    cleaned = cleaned.strip(" .,-")
    if not cleaned:
        return "Scope of work was not described in the public filing."
    cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return base.text(cleaned, 360)


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
    "non-criminal": "Non-criminal incident",
    "disorderly conduct": "Disorderly-conduct report",
    "suspicious occurrence": "Suspicious-occurrence report",
    "other miscellaneous": "Other police incident",
}

OPAQUE_POLICE_LABELS = {
    "rpd general",
    "rpd",
    "general",
    "miscellaneous",
    "other miscellaneous",
    "other",
    "none",
    "not applicable",
    "n/a",
}


def _opaque_police_label(value: Any) -> bool:
    raw = _lower(value).strip(" .,-")
    if not raw:
        return True
    if raw in OPAQUE_POLICE_LABELS:
        return True
    if re.fullmatch(r"[a-z]{2,5}\s*(general|misc|other)", raw):
        return True
    if re.fullmatch(r"\d{4,8}", raw):
        return True
    return False


def readable_police_category(value: Any) -> str:
    raw = _lower(value)
    return POLICE_CATEGORY.get(raw, _sentence(value or "Reported incident"))


def readable_police_title(category: Any, subcategory: Any, description: Any) -> str:
    blob = " ".join(_lower(x) for x in (category, subcategory, description) if _norm(x))
    if "from vehicle" in blob or "theft, from locked vehicle" in blob or "theft, from unlocked vehicle" in blob:
        return "Theft from a vehicle reported"
    if "motor vehicle theft" in blob or "vehicle, stolen" in blob or "stolen vehicle" in blob:
        return "Vehicle theft reported"
    if "vehicle recovered" in blob or "recovered vehicle" in blob:
        return "Recovered vehicle report"
    if "burglary" in blob:
        return "Burglary reported"
    if "robbery" in blob:
        return "Robbery reported"
    if "assault" in blob or "battery" in blob:
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
    if "warrant" in blob:
        return "Warrant-related incident"

    # Do not promote internal/open-data shorthand such as "RPD General" to a headline.
    sub = _norm(subcategory)
    desc = _norm(description)
    if sub and not _opaque_police_label(sub):
        cleaned = _sentence(sub)
        return cleaned if cleaned.lower().endswith(("report", "reported", "incident")) else f"{cleaned} report"
    if desc and not _opaque_police_label(desc):
        cleaned = _sentence(desc)
        return cleaned if cleaned.lower().endswith(("report", "reported", "incident")) else f"{cleaned} report"

    name = readable_police_category(category)
    if _opaque_police_label(name):
        return "Police incident report"
    if name.lower().endswith(("report", "incident", "incidents")):
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


def _permit_address(r: dict[str, Any]) -> str:
    street_number = "".join(
        part for part in (_norm(r.get("street_number")), _norm(r.get("street_number_suffix"))) if part
    )
    street = " ".join(part for part in (street_number, _norm(r.get("street_name")), _norm(r.get("street_suffix"))) if part)
    unit = "".join(part for part in (_norm(r.get("unit")), _norm(r.get("unit_suffix"))) if part)
    return f"{street}, Unit {unit}" if street and unit else street


def _permit_records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for r in rows:
        if _norm(r.get(cfg.neighborhood_field)) != hood:
            continue
        existing_units = base.unit_count(r.get("existing_units"))
        proposed_units = base.unit_count(r.get("proposed_units"))
        unit_delta = proposed_units - existing_units if existing_units is not None and proposed_units is not None else None
        raw_type = base.text(r.get("permit_type_definition") or "Building permit", 100)
        raw_scope = base.text(r.get("description"), 600)
        scope_summary = readable_permit_scope(raw_scope)
        existing_use = base.text(r.get("existing_use"), 90)
        proposed_use = base.text(r.get("proposed_use"), 90)
        estimated = base.num(r.get("estimated_cost"))
        revised = base.num(r.get("revised_cost"))
        filed_date = _date_label(r.get("filed_date"))
        status_date = _date_label(r.get("status_date"))
        status = _sentence(r.get("status"))

        context: list[str] = []
        if unit_delta is not None and unit_delta != 0:
            direction = f"+{unit_delta}" if unit_delta > 0 else str(unit_delta)
            context.append(f"Unit count: {existing_units} → {proposed_units} ({direction} proposed)")
        elif existing_units is not None and proposed_units is not None:
            context.append(f"Unit count remains {proposed_units}")
        if proposed_use and _lower(proposed_use) != _lower(existing_use):
            context.append(f"Use: {_sentence(existing_use or 'not listed')} → {_sentence(proposed_use)}")

        value_summary = ""
        if revised > 0 and abs(revised - estimated) >= 1:
            value_summary = f"Revised project value: {_money(revised)}"
            if estimated > 0:
                value_summary += f" (initial estimate {_money(estimated)})"
        elif estimated > 0:
            value_summary = f"Estimated project value: {_money(estimated)}"

        status_summary = status
        if status and status_date:
            status_summary = f"{status} · {status_date}"

        prepared.append({
            "title": readable_permit_type(raw_type),
            "raw_title": raw_type,
            "raw_description": raw_scope,
            "scope_summary": scope_summary,
            "address": _permit_address(r),
            "description": scope_summary,
            "project_context": context,
            "value_summary": value_summary,
            "cost": revised or estimated,
            "estimated_cost": estimated,
            "revised_cost": revised,
            "status": status,
            "status_summary": status_summary,
            "filed_date": filed_date,
            "permit_number": base.text(r.get("permit_number"), 40),
            "permit_type": base.text(r.get("permit_type"), 20),
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


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _police_records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    # One SFPD incident can have several incident-code rows. Group by incident number so
    # the Bulletin presents one event tile rather than making classifications look like
    # separate incidents.
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for r in rows:
        if _norm(r.get(cfg.neighborhood_field)) != hood:
            continue
        key = _norm(r.get("incident_number")) or _norm(r.get("incident_id")) or _norm(r.get("row_id"))
        if not key:
            key = "|".join(
                _norm(r.get(field))
                for field in ("incident_datetime", "intersection", "incident_category", "incident_description")
            )
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(r)

    records: list[dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        first = group[0]
        categories: list[str] = []
        titles: list[str] = []
        descriptions: list[str] = []
        codes: list[str] = []
        for r in group:
            category = readable_police_category(r.get("incident_category"))
            title = readable_police_title(r.get("incident_category"), r.get("incident_subcategory"), r.get("incident_description"))
            description = _norm(r.get("incident_description"))
            code = _norm(r.get("incident_code"))
            if category and category not in categories:
                categories.append(category)
            if title and title not in titles and title != "Police incident report":
                titles.append(title)
            if description and not _opaque_police_label(description) and description not in descriptions:
                descriptions.append(_sentence(description))
            if code and code not in codes:
                codes.append(code)

        title = titles[0] if titles else "Police incident report"
        related = [item for item in titles[1:] if item != title][:2]
        category_context = [c for c in categories if c not in {"Other police incident", "Reported incident"}]

        detail_parts: list[str] = []
        if descriptions:
            detail_parts.append("; ".join(descriptions[:2]))
        elif category_context:
            detail_parts.append("SFPD classifies this report as " + ", ".join(category_context[:3]) + ".")
        else:
            detail_parts.append("SFPD's public record does not provide a more specific plain-language incident description.")
        if related:
            detail_parts.append("Related classifications: " + "; ".join(related) + ".")

        report_type = _sentence(first.get("report_type_description"))
        filed_online = _truthy(first.get("filed_online"))
        report_method = "Filed online through SFPD" if filed_online else report_type
        occurred_at = _norm(first.get("incident_datetime"))
        occurred_display = _date_label(occurred_at, include_time=True)
        reported_display = _date_label(first.get("report_datetime"), include_time=True)
        resolution = _sentence(first.get("resolution"))

        metadata: list[str] = []
        if occurred_display:
            metadata.append(f"Occurred {occurred_display}")
        if report_method:
            metadata.append(report_method)
        if resolution:
            metadata.append(f"Resolution: {resolution}")

        records.append({
            "title": title,
            "category": ", ".join(category_context[:3]) or "Police incident",
            "description": base.text(" ".join(detail_parts), 300),
            "address": base.text(first.get("intersection"), 120),
            "status": resolution,
            "occurred_at": occurred_at,
            "occurred_display": occurred_display,
            "reported_display": reported_display,
            "report_type": report_type,
            "report_method": report_method,
            "filed_online": filed_online,
            "incident_number": _norm(first.get("incident_number")),
            "incident_id": _norm(first.get("incident_id")),
            "incident_codes": codes,
            "related_types": related,
            "metadata": metadata,
            "code_count": len(codes),
        })
        if len(records) >= 8:
            break
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
        "Raw DataSF permit descriptions are expanded from common plan-review shorthand and paired with unit/use, value and status context. "
        "Police code rows are grouped into incident-level tiles; opaque internal labels are not used as headlines, and source-published incident time, intersection, report type and resolution are shown when available."
    )
    return snapshot
