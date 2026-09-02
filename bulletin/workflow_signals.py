from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from . import analysis as base
from .permit_participants import contacts_for_row


PERMIT_TREND_DATASET_ID = "f2jc-ivnc"


def _text(value: Any, limit: int = 240) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip(" ,;:-") + "…"


def _date(value: Any) -> str:
    raw = str(value or "").strip()
    return raw[:10] if raw else ""


async def _latest_field(client, dataset_id: str, neighborhood_field: str, field: str, today: date) -> date:
    rows = await client._get(dataset_id, {
        "$select": f"max({field}) as latest",
        "$where": f"{neighborhood_field} is not null and {field} is not null and {field} <= '{client._iso_day(today, end=True)}'",
        "$limit": "1",
    })
    raw = rows[0].get("latest") if rows else None
    if not raw:
        return today - timedelta(days=1)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()


async def _daily_by_field(client, dataset_id: str, neighborhood_field: str, field: str, end_day: date, days: int = 84) -> list[dict[str, Any]]:
    start = end_day - timedelta(days=days - 1)
    day_expr = f"date_trunc_ymd({field})"
    return await client._get(dataset_id, {
        "$select": f"{neighborhood_field} as neighborhood,{day_expr} as day,count(*) as count",
        "$where": f"{neighborhood_field} is not null and {field} is not null and {field} >= '{client._iso_day(start)}' and {field} <= '{client._iso_day(end_day, end=True)}'",
        "$group": f"{neighborhood_field},{day_expr}",
        "$order": "day asc",
        "$limit": "50000",
    })


async def _permit_recent_by_field(client, dataset_id: str, field: str, end_day: date, days: int = 7) -> list[dict[str, Any]]:
    start = end_day - timedelta(days=days - 1)
    select = ",".join((
        "permit_number","permit_type_definition","filed_date","approved_date","issued_date","completed_date",
        "last_permit_activity_date","estimated_cost","revised_cost","description","status","status_date",
        "street_number","street_number_suffix","street_name","street_suffix","unit","unit_suffix",
        "existing_units","proposed_units","existing_use","proposed_use","neighborhoods_analysis_boundaries","location"
    ))
    return await client._get(dataset_id, {
        "$select": select,
        "$where": f"neighborhoods_analysis_boundaries is not null and {field} is not null and {field} >= '{client._iso_day(start)}' and {field} <= '{client._iso_day(end_day, end=True)}'",
        "$order": f"{field} desc",
        "$limit": "12000",
    })


async def _311_closed_recent(client, end_day: date, days: int = 7) -> list[dict[str, Any]]:
    start = end_day - timedelta(days=days - 1)
    select = ",".join((
        "service_request_id","requested_datetime","closed_date","updated_datetime","status_description","status_notes",
        "agency_responsible","service_name","service_subtype","service_details","address","analysis_neighborhood","lat","long"
    ))
    return await client._get("vw6y-z8j6", {
        "$select": select,
        "$where": f"analysis_neighborhood is not null and closed_date is not null and closed_date >= '{client._iso_day(start)}' and closed_date <= '{client._iso_day(end_day, end=True)}'",
        "$order": "closed_date desc",
        "$limit": "25000",
    })


async def _311_open_backlog(client) -> list[dict[str, Any]]:
    return await client._get("vw6y-z8j6", {
        "$select": "analysis_neighborhood as neighborhood,count(*) as count",
        "$where": "analysis_neighborhood is not null and status_description='Open'",
        "$group": "analysis_neighborhood",
        "$limit": "500",
    })


async def fetch_workflow_data(client, config, today: date, payload: dict[str, Any]) -> dict[str, Any]:
    if config.key == "permits":
        fields = ("filed_date", "approved_date", "issued_date", "completed_date")
        dataset_id = PERMIT_TREND_DATASET_ID
        latest_results = await asyncio.gather(*[_latest_field(client, dataset_id, config.neighborhood_field, field, today) for field in fields], return_exceptions=True)
        using_primary_view = not isinstance(latest_results[0], BaseException)
        if not using_primary_view:
            dataset_id = config.dataset_id
            latest_results = await asyncio.gather(*[_latest_field(client, dataset_id, config.neighborhood_field, field, today) for field in fields], return_exceptions=True)
        latest: dict[str, date] = {}
        fallback_latest = datetime.fromisoformat(str(payload.get("latest"))).date()
        for field, result in zip(fields, latest_results):
            latest[field] = result if isinstance(result, date) else fallback_latest
        jobs = []
        for field in fields:
            jobs.append(_daily_by_field(client, dataset_id, config.neighborhood_field, field, latest[field]))
        jobs.extend([
            _permit_recent_by_field(client, dataset_id, "approved_date", latest["approved_date"]),
            _permit_recent_by_field(client, dataset_id, "issued_date", latest["issued_date"]),
        ])
        results = await asyncio.gather(*jobs, return_exceptions=True)
        daily = {}
        for field, result in zip(fields, results[:4]):
            daily[field] = [] if isinstance(result, BaseException) else result
        approved_recent = [] if isinstance(results[4], BaseException) else results[4]
        issued_recent = [] if isinstance(results[5], BaseException) else results[5]
        lifecycle_rows = approved_recent + issued_recent
        permit_numbers = [str(row.get("permit_number") or "").strip() for row in lifecycle_rows]
        try:
            contacts = await client.permit_contacts(permit_numbers)
        except Exception:
            contacts = {}
        for row in lifecycle_rows:
            row["_permit_contacts"] = contacts.get(str(row.get("permit_number") or "").strip(), [])
        methodology = (
            "Filed, approved, issued and completed counts are separate event-date cohorts from DBI's primary-address permit view; they are not same-week conversion stages."
            if using_primary_view
            else "Lifecycle counts fell back to the main DBI permit table because the primary-address trend view was unavailable; multi-address permits can repeat in that fallback."
        )
        return {
            "kind": "permit_lifecycle",
            "latest": {field: latest[field].isoformat() for field in fields},
            "daily": daily,
            "approved_recent": approved_recent,
            "issued_recent": issued_recent,
            "using_primary_address_view": using_primary_view,
            "dataset_id": dataset_id,
            "methodology": methodology,
        }

    if config.key == "service_requests":
        latest_closed = await _latest_field(client, config.dataset_id, config.neighborhood_field, "closed_date", today)
        closed_daily, closed_recent, open_backlog = await asyncio.gather(
            _daily_by_field(client, config.dataset_id, config.neighborhood_field, "closed_date", latest_closed),
            _311_closed_recent(client, latest_closed),
            _311_open_backlog(client),
            return_exceptions=True,
        )
        return {
            "kind": "311_lifecycle",
            "latest_closed": latest_closed.isoformat(),
            "closed_daily": [] if isinstance(closed_daily, BaseException) else closed_daily,
            "closed_recent": [] if isinstance(closed_recent, BaseException) else closed_recent,
            "open_backlog": [] if isinstance(open_backlog, BaseException) else open_backlog,
            "methodology": "311 closed counts use closed_date and can include cases opened before the current seven-day request window. Open backlog is the current number of cases whose published status is Open.",
        }

    if config.key == "police":
        return {
            "kind": "police_lifecycle",
            "methodology": "SFPD Resolution is fixed at the time a report is filed. Later status changes or updates are represented through supplemental reports, so the Bulletin tracks resolution mix and supplement activity rather than a synthetic closed-case date.",
        }

    return {}


def _permit_address(row: dict[str, Any]) -> str:
    number = "".join(part for part in (str(row.get("street_number") or "").strip(), str(row.get("street_number_suffix") or "").strip()) if part)
    street = " ".join(part for part in (number, str(row.get("street_name") or "").strip(), str(row.get("street_suffix") or "").strip()) if part)
    unit = "".join(part for part in (str(row.get("unit") or "").strip(), str(row.get("unit_suffix") or "").strip()) if part)
    return f"{street}, Unit {unit}" if street and unit else street


def _permit_movement_records(rows: list[dict[str, Any]], hood: str, event_field: str, limit: int = 5) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for row in rows:
        if str(row.get("neighborhoods_analysis_boundaries") or "").strip() != hood:
            continue
        permit = _text(row.get("permit_number"), 40)
        if not permit or permit in seen:
            continue
        seen.add(permit)
        try:
            cost = max(float(row.get("revised_cost") or 0), float(row.get("estimated_cost") or 0))
        except (TypeError, ValueError):
            cost = 0.0
        contacts = contacts_for_row(row)
        owners = contacts.get("owners") or []
        contractors = contacts.get("general_contractors") or []
        out.append({
            "permit_number": permit,
            "title": _text(row.get("permit_type_definition") or "Building permit", 120),
            "address": _permit_address(row),
            "description": _text(row.get("description"), 360),
            "status": _text(row.get("status"), 80),
            "status_date": _date(row.get("status_date")),
            "filed_date": _date(row.get("filed_date")),
            "approved_date": _date(row.get("approved_date")),
            "issued_date": _date(row.get("issued_date")),
            "completed_date": _date(row.get("completed_date")),
            "event_date": _date(row.get(event_field)),
            "event": "Approved" if event_field == "approved_date" else "Issued",
            "cost": cost,
            "owners": owners,
            "general_contractors": contractors,
            "owner": owners[0]["name"] if owners else "",
            "general_contractor": contractors[0]["name"] if contractors else "",
        })
        if len(out) >= limit:
            break
    return out


def _311_closed_records(rows: list[dict[str, Any]], hood: str, limit: int = 5) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for row in rows:
        if str(row.get("analysis_neighborhood") or "").strip() != hood:
            continue
        case_id = _text(row.get("service_request_id"), 40)
        if case_id and case_id in seen:
            continue
        if case_id:
            seen.add(case_id)
        out.append({
            "case_id": case_id,
            "title": _text(row.get("service_subtype") or row.get("service_name") or "311 request", 140),
            "category": _text(row.get("service_name"), 100),
            "address": _text(row.get("address"), 140),
            "opened_date": _date(row.get("requested_datetime")),
            "closed_date": _date(row.get("closed_date")),
            "updated_date": _date(row.get("updated_datetime")),
            "status": _text(row.get("status_description"), 40),
            "status_notes": _text(row.get("status_notes"), 360),
            "agency_responsible": _text(row.get("agency_responsible"), 140),
        })
        if len(out) >= limit:
            break
    return out


def _police_snapshot(rows: list[dict[str, Any]], hood: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("analysis_neighborhood") or "").strip() != hood:
            continue
        key = str(row.get("incident_number") or row.get("incident_id") or row.get("row_id") or "").strip()
        if key:
            grouped[key].append(row)
    resolutions = Counter()
    supplement_incidents = set()
    for key, group in grouped.items():
        first = group[0]
        resolution = _text(first.get("resolution"), 80) or "Unknown"
        resolutions[resolution] += 1
        if any("supplement" in str(item.get("report_type_description") or "").lower() for item in group):
            supplement_incidents.add(key)
    total = len(grouped)
    open_active = resolutions.get("Open or Active", 0)
    actioned = sum(count for label, count in resolutions.items() if label != "Open or Active")
    return {
        "reports_in_window": total,
        "open_or_active_at_filing": open_active,
        "other_resolution_at_filing": actioned,
        "supplemental_report_incidents": len(supplement_incidents),
        "resolution_mix": [{"resolution": label, "count": count} for label, count in resolutions.most_common()],
    }


def enrich_workflow_signals(snapshot: dict[str, Any], raw_sources: list[dict[str, Any]]) -> dict[str, Any]:
    raw = {item.get("key"): item for item in raw_sources}
    permit_raw = raw.get("permits") or {}
    service_raw = raw.get("service_requests") or {}
    police_raw = raw.get("police") or {}
    permit_flow = permit_raw.get("workflow") or {}
    service_flow = service_raw.get("workflow") or {}
    police_note = (police_raw.get("workflow") or {}).get("methodology")

    open_backlog = {str(x.get("neighborhood") or "").strip(): int(base.num(x.get("count"))) for x in (service_flow.get("open_backlog") or [])}

    for edition in (snapshot.get("editions") or {}).values():
        hood = edition.get("name") or ""
        workflow = {}

        if permit_flow:
            permit_items = {}
            for key, field in (("filed","filed_date"),("approved","approved_date"),("issued","issued_date"),("completed","completed_date")):
                end_raw = (permit_flow.get("latest") or {}).get(field)
                if end_raw:
                    rows = [x for x in ((permit_flow.get("daily") or {}).get(field) or []) if str(x.get("neighborhood") or "").strip() == hood]
                    permit_items[key] = {**base.metric_stats(rows, datetime.fromisoformat(end_raw).date()), "latest": end_raw}
            workflow["permits"] = {
                **permit_items,
                "filed": (edition.get("metrics") or {}).get("permits") or {},
                "approved_recent": _permit_movement_records(permit_flow.get("approved_recent") or [], hood, "approved_date"),
                "issued_recent": _permit_movement_records(permit_flow.get("issued_recent") or [], hood, "issued_date"),
                "methodology": permit_flow.get("methodology"),
            }

        if service_flow:
            closed_end = service_flow.get("latest_closed")
            closed_metric = {}
            if closed_end:
                rows = [x for x in (service_flow.get("closed_daily") or []) if str(x.get("neighborhood") or "").strip() == hood]
                closed_metric = {**base.metric_stats(rows, datetime.fromisoformat(closed_end).date()), "latest": closed_end}
            workflow["service_requests"] = {
                "opened": (edition.get("metrics") or {}).get("service_requests") or {},
                "closed": closed_metric,
                "open_backlog": open_backlog.get(hood, 0),
                "closed_recent": _311_closed_records(service_flow.get("closed_recent") or [], hood),
                "methodology": service_flow.get("methodology"),
            }

        police = _police_snapshot(police_raw.get("recent") or [], hood)
        workflow["police"] = {
            **police,
            "methodology": police_note or "SFPD Resolution is a status at report filing; later changes are represented through supplemental reports.",
        }

        edition["workflow_signals"] = workflow

    editions = list((snapshot.get("editions") or {}).values())
    def sum_current(group: str, key: str) -> int:
        return sum(int((((edition.get("workflow_signals") or {}).get(group) or {}).get(key) or {}).get("current") or 0) for edition in editions)

    snapshot["city_workflow_signals"] = {
        "permits": {
            "filed_7d": sum_current("permits", "filed"),
            "approved_7d": sum_current("permits", "approved"),
            "issued_7d": sum_current("permits", "issued"),
            "completed_7d": sum_current("permits", "completed"),
        },
        "service_requests": {
            "opened_7d": sum(int((edition.get("metrics") or {}).get("service_requests", {}).get("current") or 0) for edition in editions),
            "closed_7d": sum_current("service_requests", "closed"),
            "open_backlog": sum(int(((edition.get("workflow_signals") or {}).get("service_requests") or {}).get("open_backlog") or 0) for edition in editions),
        },
        "police": {
            "incident_reports_7d": sum(int(((edition.get("workflow_signals") or {}).get("police") or {}).get("reports_in_window") or 0) for edition in editions),
            "open_or_active_at_filing": sum(int(((edition.get("workflow_signals") or {}).get("police") or {}).get("open_or_active_at_filing") or 0) for edition in editions),
            "supplemental_report_incidents": sum(int(((edition.get("workflow_signals") or {}).get("police") or {}).get("supplemental_report_incidents") or 0) for edition in editions),
        },
    }

    source_dates = snapshot.setdefault("source_dates", {})
    if permit_flow.get("latest"):
        permit_dates = source_dates.setdefault("permits", {})
        permit_dates.update({
            "latest_filed": (permit_flow.get("latest") or {}).get("filed_date"),
            "latest_approved": (permit_flow.get("latest") or {}).get("approved_date"),
            "latest_issued": (permit_flow.get("latest") or {}).get("issued_date"),
            "latest_completed": (permit_flow.get("latest") or {}).get("completed_date"),
        })
    if service_flow.get("latest_closed"):
        source_dates.setdefault("service_requests", {})["latest_closed"] = service_flow.get("latest_closed")

    snapshot["workflow_methodology"] = {
        "permits": permit_flow.get("methodology"),
        "service_requests": service_flow.get("methodology"),
        "police": police_note,
    }
    return snapshot