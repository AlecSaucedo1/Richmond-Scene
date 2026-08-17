from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bulletin.analysis import build_snapshot
from bulletin.config import SOURCES
from bulletin.datasf import DataSFClient
from bulletin.editorial import enrich_snapshot
from bulletin.news import NewsContextClient
from bulletin.political_quotes import build_quote_analysis
from bulletin.realestate import RealEstateClient
from bulletin.store import SnapshotStore

ROOT = Path(__file__).resolve().parent
APP_VERSION = "0.7.0"


def _hour_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(0, min(23, value))


try:
    REFRESH_TZ = ZoneInfo(os.getenv("REFRESH_TIMEZONE", "America/Los_Angeles"))
except ZoneInfoNotFoundError:
    REFRESH_TZ = ZoneInfo("America/Los_Angeles")

MORNING_REFRESH_HOUR = _hour_env("MORNING_REFRESH_HOUR", 7)
EVENING_REFRESH_HOUR = _hour_env("EVENING_REFRESH_HOUR", 18)
if EVENING_REFRESH_HOUR == MORNING_REFRESH_HOUR:
    EVENING_REFRESH_HOUR = 18 if MORNING_REFRESH_HOUR != 18 else 7

store = SnapshotStore()
client = DataSFClient()
news_client = NewsContextClient()
real_estate_client = RealEstateClient()
_snapshot = store.load()
_snapshot_lock = asyncio.Lock()
_last_error: str | None = None
_source_errors: dict[str, str] = {}
_news_error: str | None = None
_real_estate_error: str | None = None
_last_refresh_reason: str | None = None
_next_scheduled_refresh: str | None = None


def _local_now() -> datetime:
    return datetime.now(REFRESH_TZ)


def _next_refresh_time(now: datetime | None = None) -> datetime:
    now = now or _local_now()
    today = now.date()
    candidates = [
        datetime(today.year, today.month, today.day, MORNING_REFRESH_HOUR, 0, tzinfo=REFRESH_TZ),
        datetime(today.year, today.month, today.day, EVENING_REFRESH_HOUR, 0, tzinfo=REFRESH_TZ),
    ]
    future = [candidate for candidate in candidates if candidate > now]
    if future:
        return min(future)
    tomorrow = today + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, MORNING_REFRESH_HOUR, 0, tzinfo=REFRESH_TZ)


async def refresh_snapshot(reason: str = "manual") -> dict:
    global _snapshot, _last_error, _source_errors, _news_error, _real_estate_error, _last_refresh_reason
    async with _snapshot_lock:
        _last_refresh_reason = reason
        local_today = _local_now().date()
        results = await asyncio.gather(
            *(client.fetch_source(source, local_today) for source in SOURCES),
            return_exceptions=True,
        )

        successful: list[dict] = []
        source_errors: dict[str, str] = {}
        for source, result in zip(SOURCES, results):
            if isinstance(result, BaseException):
                source_errors[source.key] = f"{type(result).__name__}: {result}"
                print(f"DataSF source {source.key} failed: {source_errors[source.key]}", flush=True)
            else:
                successful.append(result)

        _source_errors = source_errors
        if not successful:
            _last_error = "All DataSF sources failed during refresh"
            if _snapshot:
                return _snapshot
            raise RuntimeError(_last_error)

        generated_at = datetime.now(timezone.utc)
        news_result, real_estate_result = await asyncio.gather(
            news_client.fetch_recent(),
            real_estate_client.fetch_recent(local_today),
            return_exceptions=True,
        )

        news_items: list[dict] = []
        if isinstance(news_result, BaseException):
            _news_error = f"{type(news_result).__name__}: {news_result}"
            print(f"Recent-news context refresh failed: {_news_error}", flush=True)
        else:
            news_items = news_result
            _news_error = None

        real_estate_data = (_snapshot or {}).get("real_estate")
        if isinstance(real_estate_result, BaseException):
            _real_estate_error = f"{type(real_estate_result).__name__}: {real_estate_result}"
            print(f"Real-estate refresh failed: {_real_estate_error}", flush=True)
        else:
            real_estate_data = real_estate_result
            _real_estate_error = None

        try:
            fresh = build_snapshot(successful, generated_at)
            enrich_snapshot(fresh, news_items, generated_at)
            fresh["real_estate"] = real_estate_data or {
                "configured": False,
                "source": "ATTOM recorder-backed sales data",
                "sales_count": 0,
                "neighborhoods": {},
                "city": {},
            }
            fresh["source_errors"] = source_errors
            fresh["available_sources"] = [item["key"] for item in successful]
            fresh["news_error"] = _news_error
            fresh["real_estate_error"] = _real_estate_error
            fresh["refresh_reason"] = reason
            store.save(fresh)
            _snapshot = fresh
            _last_error = None if not source_errors else "One or more DataSF sources are temporarily unavailable"
            print(
                f"Bulletin refreshed ({reason}) at {generated_at.isoformat()} using {len(successful)} DataSF sources",
                flush=True,
            )
            return fresh
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            print(f"Bulletin snapshot build failed: {_last_error}", flush=True)
            if _snapshot:
                return _snapshot
            raise


async def refresh_loop() -> None:
    global _next_scheduled_refresh

    try:
        await refresh_snapshot("startup")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"Startup refresh retained the last good edition: {exc}", flush=True)

    while True:
        next_run = _next_refresh_time()
        _next_scheduled_refresh = next_run.isoformat()
        delay = max(1.0, (next_run - _local_now()).total_seconds())
        print(f"Next scheduled Bulletin refresh: {_next_scheduled_refresh}", flush=True)
        try:
            await asyncio.sleep(delay)
            label = "morning" if next_run.hour == MORNING_REFRESH_HOUR else "evening"
            await refresh_snapshot(f"scheduled-{label}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Scheduled refresh retained the last good edition: {exc}", flush=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="The San Francisco Bulletin", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.filters["quote_plus"] = quote_plus


@app.get("/api/health")
async def health() -> JSONResponse:
    next_run = _next_scheduled_refresh or _next_refresh_time().isoformat()
    real_estate = (_snapshot or {}).get("real_estate") or {}
    return JSONResponse(
        {
            "ok": True,
            "version": APP_VERSION,
            "has_snapshot": bool(_snapshot),
            "generated_at": (_snapshot or {}).get("generated_at"),
            "degraded": bool(_source_errors),
            "source_errors": _source_errors,
            "news_error": _news_error,
            "real_estate_error": _real_estate_error,
            "real_estate_configured": bool(real_estate.get("configured")),
            "last_error": _last_error,
            "last_refresh_reason": _last_refresh_reason,
            "refresh_schedule": {
                "timezone": str(REFRESH_TZ),
                "morning_hour": MORNING_REFRESH_HOUR,
                "evening_hour": EVENING_REFRESH_HOUR,
                "next_scheduled_refresh": next_run,
            },
        }
    )


@app.get("/api/refresh")
async def manual_refresh() -> JSONResponse:
    fresh = await refresh_snapshot("manual")
    return JSONResponse(
        {
            "ok": True,
            "generated_at": fresh.get("generated_at"),
            "degraded": bool(_source_errors),
            "source_errors": _source_errors,
            "news_error": _news_error,
            "real_estate_error": _real_estate_error,
        }
    )


@app.get("/api/bulletin")
async def bulletin_api() -> JSONResponse:
    if not _snapshot:
        return JSONResponse(
            {"status": "building", "message": "The first edition is being assembled from DataSF."},
            status_code=202,
        )
    return JSONResponse(_snapshot)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"snapshot": _snapshot, "version": APP_VERSION},
    )


@app.get("/city", response_class=HTMLResponse)
async def city(request: Request):
    if not _snapshot:
        return templates.TemplateResponse(
            request=request,
            name="building.html",
            context={"version": APP_VERSION},
            status_code=202,
        )
    return templates.TemplateResponse(
        request=request,
        name="city.html",
        context={"snapshot": _snapshot, "city": _snapshot.get("city_analysis", {}), "version": APP_VERSION},
    )


@app.get("/real-estate", response_class=HTMLResponse)
async def real_estate(request: Request):
    if not _snapshot:
        return templates.TemplateResponse(
            request=request,
            name="building.html",
            context={"version": APP_VERSION},
            status_code=202,
        )
    return templates.TemplateResponse(
        request=request,
        name="real_estate.html",
        context={"snapshot": _snapshot, "real_estate": _snapshot.get("real_estate", {}), "version": APP_VERSION},
    )


@app.get("/city-hall", response_class=HTMLResponse)
async def city_hall(request: Request):
    if not _snapshot:
        return templates.TemplateResponse(
            request=request,
            name="building.html",
            context={"version": APP_VERSION},
            status_code=202,
        )
    analysis = build_quote_analysis(_snapshot)
    return templates.TemplateResponse(
        request=request,
        name="city_hall.html",
        context={"snapshot": _snapshot, "analysis": analysis, "version": APP_VERSION},
    )


@app.get("/neighborhood/{slug}", response_class=HTMLResponse)
async def neighborhood(request: Request, slug: str):
    if not _snapshot:
        return templates.TemplateResponse(
            request=request,
            name="building.html",
            context={"version": APP_VERSION},
            status_code=202,
        )
    edition = _snapshot.get("editions", {}).get(slug)
    if not edition:
        raise HTTPException(status_code=404, detail="Neighborhood not found")
    return templates.TemplateResponse(
        request=request,
        name="neighborhood.html",
        context={"snapshot": _snapshot, "edition": edition, "version": APP_VERSION},
    )
