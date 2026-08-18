"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

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
from .restaurant_news import fetch_neighborhood_restaurant_news as _fetch_neighborhood_restaurant_news
from .restaurant_validation import strict_verified_review_neighborhoods as _strict_verified_review_neighborhoods

_readability.readable_permit_scope = _readable_permit_scope
_analysis.build_snapshot = _readability.build_snapshot

# Preserve the original engines. The new layer increases recall, but a slow or
# temporarily unavailable auxiliary neighborhood query must not take down the
# already-working beat-specific news refresh.
_original_fetch_recent = _news.NewsContextClient.fetch_recent
_original_enrich_snapshot = _editorial.enrich_snapshot


async def _fetch_recent_deep(self, snapshot=None):
    base_items = []
    neighborhood_items = []
    base_error = None
    local_error = None
    try:
        base_items = await _original_fetch_recent(self, snapshot)
    except Exception as exc:  # retain local reporting if the broad feed fails
        base_error = exc
    try:
        neighborhood_items = await _fetch_neighborhood_news(self)
    except Exception as exc:  # retain the established feed if deep search fails
        local_error = exc

    merged = _merge_news(base_items, neighborhood_items)
    if merged:
        return merged
    # Preserve the app's existing stale-news behavior: if both retrieval paths fail,
    # raise so app.py keeps the previous successful news set and its older timestamp.
    if base_error:
        raise base_error
    if local_error:
        raise local_error
    return []


_news.NewsContextClient.fetch_recent = _fetch_recent_deep

# Keep the strict legacy validator available for compatibility. The broader dining
# fetch adds a guarded targeted-search fallback only when the result does not name
# another Bay Area city or conflicting San Francisco neighborhood.
_news._verified_review_neighborhoods = _strict_verified_review_neighborhoods


async def _fetch_restaurant_news(self):
    return await _fetch_neighborhood_restaurant_news(self)


_news.NewsContextClient.fetch_restaurant_reviews = _fetch_restaurant_news


# Preserve selective data/news crossovers, then backfill the ordinary neighborhood
# reporting module with credible local journalism. Context-only articles are labeled
# as such and never become evidence of causation for a DataSF movement.
def _enrich_snapshot_with_local_reporting(snapshot, items, generated_at=None):
    result = _original_enrich_snapshot(snapshot, items, generated_at)
    now = generated_at or datetime.now(timezone.utc)
    return _backfill_neighborhood_coverage(result, items, now)


_editorial.enrich_snapshot = _enrich_snapshot_with_local_reporting

# Happenings Near You and the full bulletin share the same dining selector.
_nearby._restaurant_review = _select_restaurant_story
