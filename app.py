from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bulletin.analysis import build_snapshot
from bulletin.config import SOURCES
from bulletin.datasf import DataSFClient
from bulletin.store import SnapshotStore

ROOT = Path(__file__).resolve().parent
REFRESH_INTERVAL_HOURS = max(1.0, float(os.getenv("REFRESH_INTERVAL_HOURS", "6")))
APP_VERSION = "0.3.0"

store = SnapshotStore()
client = DataSFClient()
_snapshot = store.load()
_snapshot_lock = asyncio.Lock()
_last_error: str | None = None
_source_errors: dict[str, str] = {}


async def refresh_snapshot() -> dict:
    global _snapshot, _last_error, _source_errors
    async with _snapshot_lock:
        results = await asyncio.gather(
            *(client.fetch_source(source, date.today()) for source in SOURCES),
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

        try:
            fresh = build_snapshot(successful, datetime.now(timezone.utc))
            fresh["source_errors"] = source_errors
            fresh["available_sources"] = [item["key"] for item in successful]
            store.save(fresh)
            _snapshot = fresh
            _last_error = None if not source_errors else "One or more DataSF sources are temporarily unavailable"
            return fresh
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            print(f"Bulletin snapshot build failed: {_last_error}", flush=True)
            if _snapshot:
                return _snapshot
            raise


async def refresh_loop() -> None:
    while True:
        try:
            await refresh_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Refresh loop retained the last good edition: {exc}", flush=True)
        await asyncio.sleep(REFRESH_INTERVAL_HOURS * 3600)


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


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "version": APP_VERSION,
            "has_snapshot": bool(_snapshot),
            "generated_at": (_snapshot or {}).get("generated_at"),
            "degraded": bool(_source_errors),
            "source_errors": _source_errors,
            "last_error": _last_error,
        }
    )


@app.get("/api/refresh")
async def manual_refresh() -> JSONResponse:
    fresh = await refresh_snapshot()
    return JSONResponse(
        {
            "ok": True,
            "generated_at": fresh.get("generated_at"),
            "degraded": bool(_source_errors),
            "source_errors": _source_errors,
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
