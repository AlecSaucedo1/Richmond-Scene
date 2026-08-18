from __future__ import annotations

from typing import Any

from . import neighborhood_coverage as coverage

_ORIGINAL_LOCATION_CONFIDENCE = coverage.location_confidence


def safe_location_confidence(item: dict[str, Any], target: str) -> tuple[str | None, int, str]:
    """Apply a cross-city guard before the normal neighborhood confidence scorer."""
    body = coverage._norm((item.get("title") or "") + " " + (item.get("summary") or ""))
    if not body:
        return None, 0, ""

    explicit = coverage._explicit_neighborhoods(body)
    other_city = next((place for place in coverage.OUTSIDE_SF_PLACES if coverage._contains(body, place)), None)

    # A phrase such as "Chinatown" or "Lincoln Park" can describe another Bay Area
    # place. If another city is named, require San Francisco context even when the
    # neighborhood word itself appears in the article snippet.
    if other_city and target in explicit and not coverage._contains(body, "San Francisco"):
        return None, 0, ""
    if other_city and target not in explicit:
        return None, 0, ""

    return _ORIGINAL_LOCATION_CONFIDENCE(item, target)
