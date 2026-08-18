from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from .config import SourceConfig


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
        """Return SFPD report-filed and incident-occurrence maxima separately.

        SFPD open data can publish a newly approved report whose underlying incident
        occurred several days earlier. Exposing both dates lets the Bulletin distinguish
        upstream publication lag from an ingestion problem.
        """
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

    async def recent_records(self, config: SourceConfig, end_day: date, days: int = 7) -> list[dict[str, Any]]:
        if not config.notable_fields:
            return []

        start_day = end_day - timedelta(days=days - 1)
        page_size = 5000
        # 311 routinely exceeds 5,000 records citywide in a seven-day window. Paginating
        # prevents later-sorted neighborhoods from disappearing from the record-level ledger.
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

        return rows

    async def fetch_source(self, config: SourceConfig, today: date) -> dict[str, Any]:
        latest = await self.latest_date(config, today)
        daily, categories, recent, source_dates = await asyncio.gather(
            self.daily_counts(config, latest),
            self.category_daily_counts(config, latest),
            self.recent_records(config, latest),
            self.police_source_dates(config, today),
        )
        return {
            "key": config.key,
            "latest": latest.isoformat(),
            "daily": daily,
            "categories": categories,
            "recent": recent,
            "source_dates": source_dates,
        }
