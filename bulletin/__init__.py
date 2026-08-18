"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

from . import analysis as _analysis
from . import nearby as _nearby
from . import readability as _readability
from .permit_scope import readable_permit_scope as _readable_permit_scope
from .restaurant_matching import select_restaurant_review as _select_restaurant_review

# Swap in the hardened scope normalizer before any snapshot is built. The
# readability module resolves this global at runtime when it constructs permit
# records, so callers can continue importing build_snapshot from bulletin.analysis.
_readability.readable_permit_scope = _readable_permit_scope
_analysis.build_snapshot = _readability.build_snapshot

# Happenings Near You must never fall back to an unrelated citywide restaurant
# review. Only reviews explicitly verified for the requested Analysis Neighborhood
# are eligible; no verified match means no restaurant-review card.
_nearby._restaurant_review = _select_restaurant_review
