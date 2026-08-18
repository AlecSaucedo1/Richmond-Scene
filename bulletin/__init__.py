"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

import asyncio
from datetime import datetime, timezone

from . import analysis as _analysis
from . import editorial as _editorial
from . import nearby as _nearby
from . import news as _news
from . import readability as _readability
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
_analysis.build_snapshot = _readability.build_snapshot

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

# Keep the legacy strict validator installed for older paths. The broadened dining
# search below adds a guarded targeted-query fallback only when no conflicting city
# or San Francisco neighborhood is named.
_news._verified_review_neighborhoods = _strict_verified_review_neighborhoods


async def _fetch_restaurant_news(self):
    direct_items = await _fetch_neighborhood_restaurant_news(self)
    event = _news_ready_event(self)
    # News and dining are launched together. Give the general neighborhood search a
    # chance to finish so restaurant stories found there can enrich the dining pool.
    # A timeout or failed general search simply leaves the direct dining results intact.
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

# Happenings Near You and the full bulletin share the same recency/outlet/location-ranked selector.
_nearby._restaurant_review = _select_restaurant_story
