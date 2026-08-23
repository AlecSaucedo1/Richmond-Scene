"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

import asyncio
from datetime import datetime, timezone

from . import analysis as _analysis
from . import arts as _arts
from . import editorial as _editorial
from . import nearby as _nearby
from . import neighborhood_coverage as _coverage
from . import news as _news
from . import readability as _readability
from . import recap_audio as _recap_audio
from . import restaurant_news as _restaurant_news_module
from .datasf import DataSFClient as _DataSFClient
from .location_safety import safe_location_confidence as _safe_location_confidence
from .map_activity import (
    build_map_activity as _build_map_activity,
    enrich_context_signals as _enrich_context_signals,
)
from .neighborhood_coverage import (
    backfill_neighborhood_coverage as _backfill_neighborhood_coverage,
    fetch_neighborhood_news as _fetch_neighborhood_news,
    merge_news as _merge_news,
)
from .permit_participants import (
    build_market_participants as _build_market_participants,
    enrich_permit_records as _enrich_permit_records,
)
from .permit_scope import readable_permit_scope as _readable_permit_scope
from .restaurant_matching import select_restaurant_review as _select_restaurant_story
from .restaurant_news import (
    fetch_neighborhood_restaurant_news as _fetch_neighborhood_restaurant_news,
    merge_restaurant_news_candidates as _merge_restaurant_news_candidates,
)
from .restaurant_validation import strict_verified_review_neighborhoods as _strict_verified_review_neighborhoods
from .store import SnapshotStore
from .storytelling import build_live_digest as _build_live_digest, enrich_storytelling as _enrich_storytelling

_readability.readable_permit_scope = _readable_permit_scope

# Live Nation's canonical San Francisco Fillmore venue identifier occasionally differs
# from older shared links. Normalize it here and keep two current major-venue events as
# dated fallbacks so the Arts calendar remains useful if dynamic calendar markup fails.
_arts.VENUE_SOURCES = tuple(
    {**source, "url": "https://www.livenation.com/venue/KovZpZAE6eeA/the-fillmore-events"}
    if source.get("name") == "The Fillmore" else source
    for source in _arts.VENUE_SOURCES
)
_arts.EVENT_SEEDS = (
    *_arts.EVENT_SEEDS,
    {
        "venue": "The Fillmore",
        "neighborhood": "Western Addition",
        "category": "Music",
        "title": "Courtney Barnett: Creature of Habit Tour",
        "start_date": "2026-08-26",
        "end_date": "2026-08-28",
        "url": "https://www.livenation.com/venue/KovZpZAE6eeA/the-fillmore-events",
        "summary": "Courtney Barnett plays a three-night run at The Fillmore.",
    },
    {
        "venue": "Chase Center",
        "neighborhood": "Mission Bay",
        "category": "Music",
        "title": "Weezer: The Gathering",
        "start_date": "2026-09-09",
        "end_date": "2026-09-09",
        "url": "https://www.chasecenter.com/events/weezer-20260909/",
        "summary": "Weezer brings The Gathering tour to Chase Center with The Shins and Silversun Pickups.",
    },
)

_original_police_records = _readability._police_records


def _police_records_with_filing_time(cfg, rows, hood):
    records = _original_police_records(cfg, rows, hood)
    for item in records:
        reported = item.get("reported_display")
        if not reported:
            continue
        metadata = list(item.get("metadata") or [])
        label = f"Reported {reported}"
        if label not in metadata:
            metadata.insert(0, label)
        item["metadata"] = metadata
    return records


_readability._police_records = _police_records_with_filing_time

_original_permit_records = _readability._permit_records


def _permit_records_with_participants(cfg, rows, hood):
    records = _original_permit_records(cfg, rows, hood)
    return _enrich_permit_records(rows, hood, cfg.neighborhood_field, records)


_readability._permit_records = _permit_records_with_participants

_original_story = _analysis.story


def _story_with_report_date_language(cfg, hood, stats, cats, recs):
    item = _original_story(cfg, hood, stats, cats, recs)
    if cfg.key != "police":
        return item
    replacements = (
        ("Reported police incidents", "Police reports filed"),
        ("reported police incidents", "police reports filed"),
        ("reported incidents", "reports filed"),
        ("seven-day source window", "seven-day report-filing window"),
    )
    for field in ("headline", "dek"):
        value = str(item.get(field) or "")
        for old, new in replacements:
            value = value.replace(old, new)
        item[field] = value
    return item


_analysis.story = _story_with_report_date_language


def _build_snapshot_with_source_dates(raw_sources, generated_at):
    snapshot = _readability.build_snapshot(raw_sources, generated_at)
    diagnostics = {}
    permit_source = None
    for source in raw_sources:
        dates = dict(source.get("source_dates") or {})
        if dates:
            diagnostics[source.get("key") or "unknown"] = dates
        if source.get("key") == "permits":
            permit_source = source
    if diagnostics:
        snapshot["source_dates"] = diagnostics
    if permit_source:
        snapshot["permit_market_participants"] = _build_market_participants(
            permit_source,
            snapshot.get("editions") or {},
            "neighborhoods_analysis_boundaries",
        )
    snapshot = _build_map_activity(snapshot, raw_sources, generated_at)
    return snapshot


_analysis.build_snapshot = _build_snapshot_with_source_dates

# Install the ambiguity/cross-city guard in both modules that score neighborhood
# location. Functions in neighborhood_coverage resolve the module global at runtime;
# restaurant_news imported the scorer by name, so update that reference as well.
_coverage.location_confidence = _safe_location_confidence
_restaurant_news_module.location_confidence = _safe_location_confidence

# Higher-value searches: favor specific changes and named local institutions over the
# generic "neighborhood" query that can return thin roundups or unrelated mentions.
_news.NEWS_QUERY_GROUPS = {
    "businesses": [
        '"San Francisco" (restaurant OR retail OR storefront OR merchant) (opening OR closing OR lease OR vacancy OR expansion) when:21d',
        '"San Francisco" (small business OR commercial corridor OR storefront) (permit OR lease OR zoning OR expansion) when:45d',
    ],
    "permits": [
        '"San Francisco" (housing OR development OR construction) (proposed OR approved OR filed OR groundbreaking OR conversion) when:30d',
        '"San Francisco" (planning commission OR rezoning OR redevelopment OR office conversion OR affordable housing) neighborhood when:60d',
    ],
    "service_requests": [
        '"San Francisco" (street OR sidewalk OR park OR transit OR public works) (closure OR construction OR repair OR cleanup OR change) neighborhood when:30d',
        '"San Francisco" (Muni OR roadwork OR plaza OR park OR sanitation) neighborhood project when:45d',
    ],
    "police": [
        '"San Francisco" SFPD (robbery OR burglary OR vehicle theft OR assault OR arrest) neighborhood when:21d',
        '"San Francisco" (police OR SFPD) neighborhood investigation arrest public safety when:30d',
    ],
}


def _better_target_query(edition, story):
    hood = str(edition.get("name") or "San Francisco").strip()
    key = story.get("source")
    records = edition.get("notable", {}).get(key, []) or []
    metric = edition.get("metrics", {}).get(key, {}) or {}
    first = records[0] if records else {}
    hood_anchor = f'"{hood}"'

    if key == "businesses" and first:
        name = str(first.get("title") or "").strip()
        address = str(first.get("address") or "").strip()
        anchors = " ".join(x for x in (f'"{name}"' if name else "", f'"{address}"' if address else "") if x)
        anchor_query = anchors or hood_anchor
        return f'{anchor_query} "San Francisco" (opening OR storefront OR restaurant OR retail OR business) when:90d'
    if key == "permits" and first:
        address = str(first.get("address") or "").strip()
        permit = str(first.get("permit_number") or "").strip()
        owner = str(first.get("owner") or "").strip()
        contractor = str(first.get("general_contractor") or "").strip()
        anchors = " ".join(
            x for x in (
                f'"{address}"' if address else "",
                f'"{permit}"' if permit else "",
                f'"{owner}"' if owner else "",
                f'"{contractor}"' if contractor else "",
            ) if x
        )
        anchor_query = anchors or hood_anchor
        return f'{anchor_query} "San Francisco" (housing OR development OR construction OR planning OR permit) when:120d'
    if key == "service_requests":
        categories = metric.get("categories") or []
        category = str(categories[0].get("display_category") or "city services") if categories else "city services"
        address = str(first.get("address") or "").strip()
        anchor = f'"{address}"' if address else hood_anchor
        return f'{anchor} "San Francisco" ({category}) (public works OR street OR park OR Muni OR neighborhood) when:90d'
    if key == "police":
        categories = metric.get("categories") or []
        category = str(categories[0].get("display_category") or "police") if categories else "police"
        intersection = str(first.get("address") or "").strip()
        anchor = f'"{intersection}"' if intersection else hood_anchor
        return f'{anchor} "San Francisco" SFPD ({category}) when:60d'
    return f'{hood_anchor} "San Francisco" (business OR housing OR transit OR school OR park OR culture OR street) when:90d'


_news._target_query = _better_target_query


def _better_neighborhood_query(neighborhood):
    terms = _coverage.NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
    quoted = " OR ".join(f'"{term}"' for term in terms[:4])
    return (
        f'({quoted}) "San Francisco" '
        '(opening OR closing OR development OR housing OR transit OR school OR park OR restaurant OR business OR culture OR street OR project) '
        'when:270d'
    )


_coverage._query = _better_neighborhood_query

_original_fetch_recent = _news.NewsContextClient.fetch_recent
_original_enrich_snapshot = _editorial.enrich_snapshot


def _news_ready_event(client):
    event = getattr(client, "_bulletin_news_ready", None)
    if event is None:
        event = asyncio.Event()
        client._bulletin_news_ready = event
    return event


async def _fetch_recent_deep(self, snapshot=None):
    event = _news_ready_event(self)
    event.clear()
    base_items = []
    neighborhood_items = []
    base_error = None
    local_error = None
    try:
        try:
            base_items = await _original_fetch_recent(self, snapshot)
        except Exception as exc:
            base_error = exc
        try:
            neighborhood_items = await _fetch_neighborhood_news(self)
        except Exception as exc:
            local_error = exc

        merged = _merge_news(base_items, neighborhood_items)
        self._bulletin_latest_news_items = merged
        if merged:
            return merged
        if base_error:
            raise base_error
        if local_error:
            raise local_error
        return []
    finally:
        event.set()


_news.NewsContextClient.fetch_recent = _fetch_recent_deep

_news._verified_review_neighborhoods = _strict_verified_review_neighborhoods


async def _fetch_restaurant_news(self):
    direct_items = await _fetch_neighborhood_restaurant_news(self)
    event = _news_ready_event(self)
    try:
        await asyncio.wait_for(event.wait(), timeout=20)
    except asyncio.TimeoutError:
        pass
    news_items = list(getattr(self, "_bulletin_latest_news_items", []) or [])
    return _merge_restaurant_news_candidates(direct_items, news_items)


_news.NewsContextClient.fetch_restaurant_reviews = _fetch_restaurant_news


def _enrich_snapshot_with_local_reporting(snapshot, items, generated_at=None):
    result = _original_enrich_snapshot(snapshot, items, generated_at)
    now = generated_at or datetime.now(timezone.utc)
    result = _backfill_neighborhood_coverage(result, items, now)
    try:
        previous = SnapshotStore().load()
    except Exception:
        previous = None
    result = _enrich_storytelling(result, previous, now)
    result["live_digest"] = _build_live_digest(result, items, previous, now)
    return result


_editorial.enrich_snapshot = _enrich_snapshot_with_local_reporting

_nearby._restaurant_review = _select_restaurant_story

# App.py calls BulletinBriefAudioClient.generate only after real-estate and arts data
# have been attached to the fresh snapshot. Use that stable point in the refresh flow
# to add those optional mapped signals without making them part of the core DataSF
# snapshot transaction. Failures are nonblocking; the public-record map remains intact.
_map_datasf_client = _DataSFClient()
_original_brief_generate = _recap_audio.BulletinBriefAudioClient.generate


async def _brief_generate_with_map_context(self, snapshot):
    try:
        await _enrich_context_signals(snapshot, _map_datasf_client, datetime.now(timezone.utc))
    except Exception as exc:
        print(f"Optional map context enrichment failed: {type(exc).__name__}: {exc}", flush=True)
    return await _original_brief_generate(self, snapshot)


_recap_audio.BulletinBriefAudioClient.generate = _brief_generate_with_map_context
