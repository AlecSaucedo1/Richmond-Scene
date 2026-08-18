"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

from . import analysis as _analysis
from . import nearby as _nearby
from . import news as _news
from . import readability as _readability
from .permit_scope import readable_permit_scope as _readable_permit_scope
from .restaurant_matching import select_restaurant_review as _select_restaurant_story
from .restaurant_news import fetch_neighborhood_restaurant_news as _fetch_neighborhood_restaurant_news
from .restaurant_validation import strict_verified_review_neighborhoods as _strict_verified_review_neighborhoods

# Swap in the hardened scope normalizer before any snapshot is built. The
# readability module resolves this global at runtime when it constructs permit
# records, so callers can continue importing build_snapshot from bulletin.analysis.
_readability.readable_permit_scope = _readable_permit_scope
_analysis.build_snapshot = _readability.build_snapshot

# Restaurant search placement is not accepted as proof of location. Results must
# explicitly name the Analysis Neighborhood and avoid cross-city conflicts.
_news._verified_review_neighborhoods = _strict_verified_review_neighborhoods

# Keep the existing twice-daily refresh contract but broaden the legacy review job
# into recent neighborhood restaurant coverage: reviews, openings, closures,
# chef/menu stories and other useful dining reporting can qualify.
async def _fetch_restaurant_news(self):
    return await _fetch_neighborhood_restaurant_news(self)

_news.NewsContextClient.fetch_restaurant_reviews = _fetch_restaurant_news

# Happenings Near You uses the same strict neighborhood selector as the bulletin.
_nearby._restaurant_review = _select_restaurant_story
