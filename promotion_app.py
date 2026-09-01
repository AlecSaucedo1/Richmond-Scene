from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

import app as core
from bulletin.promotion import (
    INDEXNOW_KEY,
    PUBLIC_BASE_URL,
    build_city_feed,
    build_neighborhood_feed,
    build_sitemap,
    notify_indexnow,
    robots_txt,
)
from bulletin.social_card import build_social_card_png
from bulletin.longread_ai import IntelligentLongReadClient


app = core.app
_original_refresh_snapshot = core.refresh_snapshot
long_read_client = IntelligentLongReadClient()


async def _refresh_with_promotion(reason: str = "manual") -> dict[str, Any]:
    previous = core._snapshot
    fresh = await _original_refresh_snapshot(reason)
    if previous:
        # Keep the last completed analysis visible while the new daily batch is generated.
        fresh["long_reads"] = (previous.get("long_reads") or {})
        fresh["long_read_meta"] = (previous.get("long_read_meta") or {})
    fresh = await long_read_client.enrich(fresh, previous)
    result = await notify_indexnow(fresh)
    fresh["promotion"] = {
        "public_base_url": PUBLIC_BASE_URL,
        "sitemap_url": f"{PUBLIC_BASE_URL}/sitemap.xml",
        "rss_url": f"{PUBLIC_BASE_URL}/feed.xml",
        "indexnow": result,
    }
    # The core refresh has already stored a valid snapshot. Persisting promotion
    # diagnostics a second time is intentionally best-effort and can never make
    # the Bulletin refresh fail.
    try:
        core.store.save(fresh)
        core._snapshot = fresh
    except Exception as exc:
        print(f"Promotion metadata save failed: {type(exc).__name__}: {exc}", flush=True)
    return fresh


# app.refresh_loop resolves this global dynamically inside the app module, so replacing
# it here means startup, morning, evening and manual refreshes all get the same discovery
# notification behavior without creating a second scheduler.
core.refresh_snapshot = _refresh_with_promotion


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> Response:
    return Response(robots_txt(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap() -> Response:
    return Response(build_sitemap(core._snapshot), media_type="application/xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800"})


@app.get("/feed.xml", include_in_schema=False)
async def city_feed() -> Response:
    return Response(build_city_feed(core._snapshot), media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=900"})


@app.get("/neighborhood/{slug}/feed.xml", include_in_schema=False)
async def neighborhood_feed(slug: str) -> Response:
    content = build_neighborhood_feed(core._snapshot, slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Neighborhood not found")
    return Response(content, media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=900"})


@app.get("/social-card.png", include_in_schema=False)
async def social_card() -> Response:
    return Response(build_social_card_png(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get(f"/{INDEXNOW_KEY}.txt", include_in_schema=False)
async def indexnow_key() -> Response:
    return Response(INDEXNOW_KEY, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/promotion", include_in_schema=False)
async def promotion_status() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "public_base_url": PUBLIC_BASE_URL,
        "sitemap": f"{PUBLIC_BASE_URL}/sitemap.xml",
        "rss": f"{PUBLIC_BASE_URL}/feed.xml",
        "social_card": f"{PUBLIC_BASE_URL}/social-card.png",
        "long_read_meta": (core._snapshot or {}).get("long_read_meta") or {},
        "promotion": (core._snapshot or {}).get("promotion") or {},
    })
