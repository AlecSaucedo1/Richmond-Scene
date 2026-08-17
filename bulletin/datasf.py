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

    async def _get(self, dataset_id: str, params: dict[str, str]) -> list[dict[str, Any]]:
        headers = {"User-Agent": "sf-neighborhood-bulletin/0.1"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        url = f"{self.base_url}/{dataset_id}.json"
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"Unexpected DataSF response for {dataset_id}")
            return payload

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
        params = {
            "$select": ",".join(config.notable_fields),
            "$where": (
                f"{config.neighborhood_field} is not null and "
                f"{config.date_field} >= '{self._iso_day(start_day)}' and "
                f"{config.date_field} <= '{self._iso_day(end_day, end=True)}'"
            ),
            "$order": f"{config.date_field} desc",
            "$limit": "5000",
        }
        return await self._get(config.dataset_id, params)

    async def fetch_source(self, config: SourceConfig, today: date) -> dict[str, Any]:
        latest = await self.latest_date(config, today)
        daily, categories, recent = await asyncio.gather(
            self.daily_counts(config, latest),
            self.category_daily_counts(config, latest),
            self.recent_records(config, latest),
        )
        return {
            "key": config.key,
            "latest": latest.isoformat(),
            "daily": daily,
            "categories": categories,
            "recent": recent,
        }
