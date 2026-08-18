"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

from . import analysis as _analysis
from . import readability as _readability
from .permit_scope import readable_permit_scope as _readable_permit_scope

# Swap in the hardened scope normalizer before any snapshot is built. The
# readability module resolves this global at runtime when it constructs permit
# records, so callers can continue importing build_snapshot from bulletin.analysis.
_readability.readable_permit_scope = _readable_permit_scope
_analysis.build_snapshot = _readability.build_snapshot
