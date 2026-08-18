"""Bulletin package initialization.

Keep the public analysis API stable while layering reader-friendly labels and
record context over the underlying trend calculations.
"""

from . import analysis as _analysis
from .readability import build_snapshot as _readable_build_snapshot

_analysis.build_snapshot = _readable_build_snapshot
