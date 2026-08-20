from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).lower()).strip()


def _contact_name(contact: dict[str, Any]) -> str:
    firm = _text(contact.get("firm_name"))
    person = " ".join(part for part in (_text(contact.get("first_name")), _text(contact.get("last_name"))) if part)
    return firm or person


def _role_kind(role: Any) -> str | None:
    """Classify only roles DBI actually labels as owner or general contractor.

    A generic Contractor role is treated as the permit's contractor contact; explicit
    subcontractor roles are excluded from the general-contractor bucket. We preserve
    the raw DBI role on every contact so the UI can stay transparent about source labels.
    """
    raw = _norm(role)
    if not raw:
        return None
    if "owner" in raw:
        return "owner"
    if "subcontract" in raw:
        return None
    if raw in {"contractor", "general contractor", "general building contractor", "prime contractor"}:
        return "general_contractor"
    if "general contractor" in raw or "prime contractor" in raw:
        return "general_contractor"
    return None


def contacts_for_row(row: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    output: dict[str, list[dict[str, str]]] = {"owners": [], "general_contractors": []}
    seen: dict[str, set[str]] = {"owners": set(), "general_contractors": set()}
    for contact in row.get("_permit_contacts") or []:
        kind = _role_kind(contact.get("role"))
        name = _contact_name(contact)
        if not kind or not name:
            continue
        key = "owners" if kind == "owner" else "general_contractors"
        normalized = _norm(name)
        if normalized in seen[key]:
            continue
        seen[key].add(normalized)
        output[key].append({
            "name": name,
            "role": _text(contact.get("role")),
        })
    return output


def enrich_permit_records(rows: list[dict[str, Any]], hood: str, neighborhood_field: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_permit: dict[str, dict[str, list[dict[str, str]]]] = {}
    for row in rows:
        if _text(row.get(neighborhood_field)) != hood:
            continue
        permit_number = _text(row.get("permit_number"))
        if not permit_number or permit_number in by_permit:
            continue
        by_permit[permit_number] = contacts_for_row(row)

    for item in records:
        permit_number = _text(item.get("permit_number"))
        contacts = by_permit.get(permit_number) or {"owners": [], "general_contractors": []}
        owners = contacts["owners"]
        contractors = contacts["general_contractors"]
        item["owners"] = owners
        item["general_contractors"] = contractors
        item["owner"] = owners[0]["name"] if owners else ""
        item["general_contractor"] = contractors[0]["name"] if contractors else ""
        item["permit_contacts_available"] = bool(row_contacts := (owners or contractors))

        context = list(item.get("project_context") or [])
        if owners:
            label = ", ".join(contact["name"] for contact in owners[:2])
            context.append(f"Owner listed by DBI: {label}")
        if contractors:
            label = ", ".join(contact["name"] for contact in contractors[:2])
            context.append(f"General contractor listed by DBI: {label}")
        item["project_context"] = context
    return records


def _participant_counts(rows: list[dict[str, Any]], neighborhood_field: str, hood: str | None = None) -> dict[str, dict[str, set[str]]]:
    counts: dict[str, dict[str, set[str]]] = {
        "owners": defaultdict(set),
        "general_contractors": defaultdict(set),
    }
    seen_permits: set[str] = set()
    for row in rows:
        if hood is not None and _text(row.get(neighborhood_field)) != hood:
            continue
        permit_number = _text(row.get("permit_number"))
        if not permit_number or permit_number in seen_permits:
            continue
        seen_permits.add(permit_number)
        contacts = contacts_for_row(row)
        for key in ("owners", "general_contractors"):
            for contact in contacts[key]:
                counts[key][_text(contact["name"])].add(permit_number)
    return counts


def _rank(local: dict[str, set[str]], city: dict[str, set[str]], limit: int = 6) -> list[dict[str, Any]]:
    rows = []
    for name, permits in local.items():
        rows.append({
            "name": name,
            "filings": len(permits),
            "citywide_filings": len(city.get(name, set())),
            "repeat_participant": len(permits) >= 2 or len(city.get(name, set())) >= 2,
        })
    rows.sort(key=lambda item: (item["filings"], item["citywide_filings"], item["name"].lower()), reverse=True)
    return rows[:limit]


def build_market_participants(raw_permit_source: dict[str, Any], editions: dict[str, dict[str, Any]], neighborhood_field: str) -> dict[str, Any]:
    rows = raw_permit_source.get("recent") or []
    city = _participant_counts(rows, neighborhood_field)
    by_neighborhood: dict[str, dict[str, Any]] = {}

    for edition in editions.values():
        hood = edition.get("name") or ""
        local = _participant_counts(rows, neighborhood_field, hood)
        summary = {
            "owners": _rank(local["owners"], city["owners"]),
            "general_contractors": _rank(local["general_contractors"], city["general_contractors"]),
            "source": "DataSF Building Permits Contacts",
            "window": "Current seven-day permit filing window",
            "note": (
                "Participants are DBI permit contacts joined by permit number. 'Owner' reflects the role listed on the permit contact record and is not an assessor/title ownership determination. "
                "General-contractor counts exclude contacts explicitly labeled as subcontractors. Counts are distinct permit filings."
            ),
        }
        edition["permit_market_participants"] = summary
        by_neighborhood[hood] = summary

    city_summary = {
        "owners": _rank(city["owners"], city["owners"], limit=10),
        "general_contractors": _rank(city["general_contractors"], city["general_contractors"], limit=10),
    }
    return {
        "city": city_summary,
        "neighborhoods": by_neighborhood,
        "source": "DataSF Building Permits Contacts",
        "window": "Current seven-day permit filing window",
    }
