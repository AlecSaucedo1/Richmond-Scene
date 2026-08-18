"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

import asyncio
from datetime import datetime, timezone

from . import analysis as _analysis
from . import editorial as _editorial
from . import nearby as _nearby
from . import neighborhood_coverage as _coverage
from . import news as _news
from . import readability as _readability
from . import restaurant_news as _restaurant_news_module
from .location_safety import safe_location_confidence as _safe_location_confidence
from .neighborhood_coverage import (
    backfill_neighborhood_coverage as _backfill_neighborhood_coverage,
    fetch_neighborhood_news as _fetch_neighborhood_news,
    merge_news as _merge_news,
)
from .permit_scope import readable_permit_scope as _readable_permit_scope
from .restaurant_matching import select_restaurant_review as _select_restaurant_story
from .restaurant_news import (
    fetch_neighborhood_restaurant_news as _fetch_neighborhood_restaurant_news,
    merge_restaurant_news_candidates as _merge_restaurant_news_candidates,
)
from .restaurant_validation import strict_verified_review_neighborhoods as _strict_verified_review_neighborhoods

_readability.readable_permit_scope = _readable_permit_scope

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
    for source in raw_sources:
        dates = dict(source.get("source_dates") or {})
        if dates:
            diagnostics[source.get("key") or "unknown"] = dates
    if diagnostics:
        snapshot["source_dates"] = diagnostics
    return snapshot


_analysis.build_snapshot = _build_snapshot_with_source_dates

# Install the ambiguity/cross-city guard in both modules that score neighborhood
# location. Functions in neighborhood_coverage resolve the module global at runtime;
# restaurant_news imported the scorer by name, so update that reference as well.
_coverage.location_confidence = _safe_location_confidence
_restaurant_news_module.location_confidence = _safe_location_confidence

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
    return _backfill_neighborhood_coverage(result, items, now)


_editorial.enrich_snapshot = _enrich_snapshot_with_local_reporting

_nearby._restaurant_review = _select_restaurant_story
