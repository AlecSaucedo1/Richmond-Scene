from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from .config import SourceConfig


PERMIT_CONTACTS_DATASET_ID = "3pee-9qhc"
ADDRESS_DATASET_ID = "5mjj-njit"
NEIGHBORHOOD_BOUNDARY_DATASET_ID = "j2bu-swwd"


class DataSFClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("DATASF_BASE_URL", "https://data.sfgov.org/resource").rstrip("/")
        self.app_token = os.getenv("DATASF_APP_TOKEN", "").strip()
        self.timeout = float(os.getenv("DATASF_TIMEOUT_SECONDS", "30"))
        self.max_retries = max(1, int(os.getenv("DATASF_MAX_RETRIES", "3")))

    async def _get(self, dataset_id: str, params: dict[str, str]) -> list[dict[str, Any]]:
        headers = {"User-Agent": "sf-neighborhood-bulletin/1.2"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        url = f"{self.base_url}/{dataset_id}.json"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
                    response = await client.get(url, params=params)

                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt < self.max_retries - 1:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after else float(2 ** attempt)
                        except ValueError:
                            delay = float(2 ** attempt)
                        await asyncio.sleep(min(delay, 8.0))
                        continue

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise RuntimeError(f"Unexpected DataSF response for {dataset_id}")
                return payload
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(float(2 ** attempt), 8.0))
                    continue
                raise
            except Exception as exc:
                last_error = exc
                raise

        raise RuntimeError(f"DataSF request failed for {dataset_id}: {last_error}")

    @staticmethod
    def _iso_day(day: date, end: bool = False) -> str:
        suffix = "T23:59:59" if end else "T00:00:00"
        return day.isoformat() + suffix

    @staticmethod
    def _permit_address(row: dict[str, Any]) -> str:
        number = "".join(
            part for part in (
                str(row.get("street_number") or "").strip(),
                str(row.get("street_number_suffix") or "").strip(),
            ) if part
        )
        return " ".join(
            part for part in (
                number,
                str(row.get("street_name") or "").strip(),
                str(row.get("street_suffix") or "").strip(),
            ) if part
        ).strip()

    @staticmethod
    def _norm_address(value: Any) -> str:
        return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()

    @staticmethod
    def _unit_count(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    async def latest_date(self, config: SourceConfig, today: date) -> date:
        params = {
            "$select": f"max({config.date_field}) as latest",
            "$where": (
                f"{config.neighborhood_field} is not null and "
                f"{config.date_field} <= '{self._iso_day(today, end=True)}'"
            ),
            "$limit": "1",
        }
        rows = await self._get(config.dataset_id, params)
        raw = rows[0].get("latest") if rows else None
        if not raw:
            return today - timedelta(days=1)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()

    async def police_source_dates(self, config: SourceConfig, today: date) -> dict[str, str | None]:
        """Return SFPD report-filed and incident-occurrence maxima separately."""
        if config.key != "police":
            return {}
        params = {
            "$select": "max(report_datetime) as latest_report,max(incident_datetime) as latest_incident",
            "$where": (
                f"{config.neighborhood_field} is not null and "
                f"report_datetime <= '{self._iso_day(today, end=True)}' and "
                f"incident_datetime <= '{self._iso_day(today, end=True)}'"
            ),
            "$limit": "1",
        }
        rows = await self._get(config.dataset_id, params)
        row = rows[0] if rows else {}
        return {
            "latest_report": row.get("latest_report"),
            "latest_incident": row.get("latest_incident"),
        }

    async def daily_counts(self, config: SourceConfig, end_day: date, days: int = 84) -> list[dict[str, Any]]:
        start_day = end_day - timedelta(days=days - 1)
        day_expr = f"date_trunc_ymd({config.date_field})"
        params = {
            "$select": f"{config.neighborhood_field} as neighborhood,{day_expr} as day,count(*) as count",
            "$where": (
                f"{config.neighborhood_field} is not null and "
                f"{config.date_field} >= '{self._iso_day(start_day)}' and "
                f"{config.date_field} <= '{self._iso_day(end_day, end=True)}'"
            ),
            "$group": f"{config.neighborhood_field},{day_expr}",
            "$order": "day asc",
            "$limit": "50000",
        }
        return await self._get(config.dataset_id, params)

    async def category_daily_counts(self, config: SourceConfig, end_day: date, days: int = 35) -> list[dict[str, Any]]:
        if not config.category_field:
            return []
        start_day = end_day - timedelta(days=days - 1)
        day_expr = f"date_trunc_ymd({config.date_field})"
        params = {
            "$select": (
                f"{config.neighborhood_field} as neighborhood,{config.category_field} as category,"
                f"{day_expr} as day,count(*) as count"
            ),
            "$where": (
                f"{config.neighborhood_field} is not null and {config.category_field} is not null and "
                f"{config.date_field} >= '{self._iso_day(start_day)}' and "
                f"{config.date_field} <= '{self._iso_day(end_day, end=True)}'"
            ),
            "$group": f"{config.neighborhood_field},{config.category_field},{day_expr}",
            "$order": "day asc",
            "$limit": "100000",
        }
        return await self._get(config.dataset_id, params)

    async def permit_contacts(self, permit_numbers: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Fetch DBI contacts for recent building permits without changing permit counts."""
        cleaned = list(dict.fromkeys(str(value or "").strip() for value in permit_numbers if str(value or "").strip()))
        if not cleaned:
            return {}

        contacts: dict[str, list[dict[str, Any]]] = {}
        chunk_size = 60
        for start in range(0, len(cleaned), chunk_size):
            chunk = cleaned[start : start + chunk_size]
            escaped = [value.replace("'", "''") for value in chunk]
            where = "permit_number in (" + ",".join(f"'{value}'" for value in escaped) + ")"
            rows = await self._get(
                PERMIT_CONTACTS_DATASET_ID,
                {
                    "$select": "permit_number,first_name,last_name,role,firm_name",
                    "$where": where,
                    "$limit": "5000",
                },
            )
            for row in rows:
                permit_number = str(row.get("permit_number") or "").strip()
                if permit_number:
                    contacts.setdefault(permit_number, []).append(row)
        return contacts

    def _permit_map_candidates(self, rows: list[dict[str, Any]]) -> list[str]:
        by_neighborhood: dict[str, list[tuple[float, str]]] = {}
        for row in rows:
            neighborhood = str(row.get("neighborhoods_analysis_boundaries") or "").strip()
            address = self._permit_address(row)
            if not neighborhood or not address:
                continue
            existing = self._unit_count(row.get("existing_units"))
            proposed = self._unit_count(row.get("proposed_units"))
            unit_delta = max((proposed - existing) if existing is not None and proposed is not None else 0, 0)
            try:
                cost = max(float(row.get("revised_cost") or 0), float(row.get("estimated_cost") or 0))
            except (TypeError, ValueError):
                cost = 0.0
            score = unit_delta * 1_000_000_000 + cost
            by_neighborhood.setdefault(neighborhood, []).append((score, address))

        output: list[str] = []
        for values in by_neighborhood.values():
            values.sort(key=lambda item: item[0], reverse=True)
            output.extend(address for _, address in values[:6])
        return list(dict.fromkeys(output))

    async def permit_map_points(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        addresses = self._permit_map_candidates(rows)
        if not addresses:
            return {}
        matches: dict[str, dict[str, Any]] = {}
        chunk_size = 30
        for start in range(0, len(addresses), chunk_size):
            chunk = addresses[start : start + chunk_size]
            clauses = []
            for address in chunk:
                escaped = address.upper().replace("'", "''")
                clauses.append(f"upper(address) like '{escaped}%'")
            found = await self._get(
                ADDRESS_DATASET_ID,
                {
                    "$select": "address,point",
                    "$where": " OR ".join(clauses),
                    "$limit": "3000",
                },
            )
            for row in found:
                point = row.get("point")
                if not point:
                    continue
                row_norm = self._norm_address(row.get("address"))
                for requested in chunk:
                    request_norm = self._norm_address(requested)
                    if request_norm and row_norm.startswith(request_norm):
                        matches.setdefault(request_norm, point)
        return matches

    async def neighborhood_boundaries(self) -> dict[str, Any]:
        rows = await self._get(
            NEIGHBORHOOD_BOUNDARY_DATASET_ID,
            {"$select": "nhood,the_geom", "$limit": "100"},
        )
        return {
            str(row.get("nhood") or "").strip(): row.get("the_geom")
            for row in rows
            if row.get("nhood") and row.get("the_geom")
        }

    async def recent_records(self, config: SourceConfig, end_day: date, days: int = 7) -> list[dict[str, Any]]:
        if not config.notable_fields:
            return []

        start_day = end_day - timedelta(days=days - 1)
        page_size = 5000
        max_rows = 25000 if config.key == "service_requests" else 10000
        rows: list[dict[str, Any]] = []
        offset = 0

        while len(rows) < max_rows:
            params = {
                "$select": ",".join(config.notable_fields),
                "$where": (
                    f"{config.neighborhood_field} is not null and "
                    f"{config.date_field} >= '{self._iso_day(start_day)}' and "
                    f"{config.date_field} <= '{self._iso_day(end_day, end=True)}'"
                ),
                "$order": f"{config.date_field} desc",
                "$limit": str(min(page_size, max_rows - len(rows))),
                "$offset": str(offset),
            }
            page = await self._get(config.dataset_id, params)
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)

        if config.key == "permits" and rows:
            permit_numbers = [str(row.get("permit_number") or "").strip() for row in rows]
            contacts_result, points_result = await asyncio.gather(
                self.permit_contacts(permit_numbers),
                self.permit_map_points(rows),
                return_exceptions=True,
            )
            if isinstance(contacts_result, BaseException):
                print(f"DBI permit-contact enrichment failed: {type(contacts_result).__name__}: {contacts_result}", flush=True)
                by_permit = {}
            else:
                by_permit = contacts_result
            if isinstance(points_result, BaseException):
                print(f"DBI permit-map enrichment failed: {type(points_result).__name__}: {points_result}", flush=True)
                by_address = {}
            else:
                by_address = points_result

            for row in rows:
                permit_number = str(row.get("permit_number") or "").strip()
                row["_permit_contacts"] = by_permit.get(permit_number, [])
                address_key = self._norm_address(self._permit_address(row))
                if address_key in by_address:
                    row["_map_point"] = by_address[address_key]

        return rows

    async def fetch_source(self, config: SourceConfig, today: date) -> dict[str, Any]:
        latest = await self.latest_date(config, today)
        boundary_job = self.neighborhood_boundaries() if config.key == "permits" else asyncio.sleep(0, result={})
        daily, categories, recent, source_dates, map_boundaries = await asyncio.gather(
            self.daily_counts(config, latest),
            self.category_daily_counts(config, latest),
            self.recent_records(config, latest),
            self.police_source_dates(config, today),
            boundary_job,
        )
        return {
            "key": config.key,
            "latest": latest.isoformat(),
            "daily": daily,
            "categories": categories,
            "recent": recent,
            "source_dates": source_dates,
            "map_boundaries": map_boundaries,
        }
