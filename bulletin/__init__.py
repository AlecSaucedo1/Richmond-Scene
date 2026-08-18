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

# Swap in the hardened scope normalizer before any snapshot is built. The
# readability module resolves this global at runtime when it constructs permit
# records, so callers can continue importing build_snapshot from bulletin.analysis.
_readability.readable_permit_scope = _readable_permit_scope
_analysis.build_snapshot = _readability.build_snapshot

# Keep the original news functions so the enrichment layer adds recall instead of
# replacing the existing beat-specific and data-targeted searches.
_original_fetch_recent = _news.NewsContextClient.fetch_recent
_original_enrich_snapshot = _editorial.enrich_snapshot


async def _fetch_recent_deep(self, snapshot=None):
    base_items = await _original_fetch_recent(self, snapshot)
    neighborhood_items = await _fetch_neighborhood_news(self)
    return _merge_news(base_items, neighborhood_items)


_news.NewsContextClient.fetch_recent = _fetch_recent_deep


# Restaurant search placement is not accepted as proof of location by itself in the
# legacy verifier. The broader dining fetch below adds a second, guarded fallback
# only when the targeted result does not identify another city or SF neighborhood.
_news._verified_review_neighborhoods = _strict_verified_review_neighborhoods


# Keep the existing twice-daily refresh contract but broaden the legacy review job
# into recent neighborhood restaurant coverage: reviews, openings, closures,
# chef/menu stories and other useful dining reporting can qualify.
async def _fetch_restaurant_news(self):
    return await _fetch_neighborhood_restaurant_news(self)


_news.NewsContextClient.fetch_restaurant_reviews = _fetch_restaurant_news


# Preserve the selective data/news crossover produced by editorial.py, then fill a
# neighborhood's Recent Reporting module with credible local journalism when the
# current data signal does not have a strong causal/context match. This prevents an
# empty neighborhood-news section without weakening citywide crossover standards.
def _enrich_snapshot_with_local_reporting(snapshot, items, generated_at=None):
    result = _original_enrich_snapshot(snapshot, items, generated_at)
    now = generated_at or datetime.now(timezone.utc)
    return _backfill_neighborhood_coverage(result, items, now)


_editorial.enrich_snapshot = _enrich_snapshot_with_local_reporting


# Happenings Near You uses the same recency/outlet/location-ranked dining selector as
# the full neighborhood bulletin.
_nearby._restaurant_review = _select_restaurant_story
