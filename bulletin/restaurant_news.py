from __future__ import annotations

import asyncio
from typing import Any

from .config import ANALYSIS_NEIGHBORHOODS
from .neighborhood_coverage import location_confidence, publisher_score
from .news import RESTAURANT_LANGUAGE, RESTAURANT_NEIGHBORHOOD_TERMS, _article_key


def _query(neighborhood: str) -> str:
    terms = RESTAURANT_NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
    anchors = " OR ".join(f'"{term}"' for term in terms[:3])
    # Keep a long enough horizon to avoid empty editions. Google News still returns
    # the newest matching items first, and ranking below heavily favors recency.
    return (
        f'({anchors}) "San Francisco" '
        '(restaurant OR cafe OR dining OR chef OR menu OR food OR bakery OR bar) when:365d'
    )


def _story_type(item: dict[str, Any]) -> str:
    body = ((item.get("title") or "") + " " + (item.get("summary") or "")).lower()
    if any(term in body for term in ("review", "critic", "rated", "rating")):
        return "Restaurant review"
    if any(term in body for term in ("close", "closing", "closed", "shutter")):
        return "Restaurant closure"
    if any(term in body for term in ("open", "opening", "debut", "launch")):
        return "Restaurant opening"
    if any(term in body for term in ("chef", "menu", "owner", "ownership", "expansion", "profile")):
        return "Restaurant news"
    return "Neighborhood dining"


def _confidence_weight(confidence: str | None) -> int:
    return {
        "explicit": 42,
        "targeted_notable": 28,
        "targeted_sf": 21,
        "targeted_search": 12,
    }.get(confidence or "", 0)


async def fetch_neighborhood_restaurant_news(client) -> list[dict]:
    jobs = [(neighborhood, _query(neighborhood)) for neighborhood in ANALYSIS_NEIGHBORHOODS]
    fetched = await asyncio.gather(
        *(client._feed("restaurant_reviews", query, neighborhood) for neighborhood, query in jobs),
        return_exceptions=True,
    )

    deduped: dict[str, dict] = {}
    for (neighborhood, _), result in zip(jobs, fetched):
        if isinstance(result, BaseException):
            continue
        for item in result:
            text = (item.get("title") or "") + " " + (item.get("summary") or "")
            if not RESTAURANT_LANGUAGE.search(text):
                continue

            # The result must either name the neighborhood directly or survive the
            # targeted-search fallback checks in neighborhood_coverage. Those checks
            # reject another Bay Area city and conflicting SF-neighborhood evidence.
            confidence, location_score, evidence = location_confidence(item, neighborhood)
            if not confidence:
                continue

            enriched = {
                **item,
                "verified_neighborhoods": [neighborhood],
                "neighborhood_evidence": {neighborhood: evidence},
                "neighborhood_confidence": {neighborhood: confidence},
                "neighborhood_location_score": {neighborhood: location_score},
                "restaurant_verified": True,
                # Keep the legacy flag while older cached clients transition.
                "review_verified": True,
                "restaurant_story_type": _story_type(item),
                "restaurant_source_score": publisher_score(item),
                "restaurant_confidence_score": _confidence_weight(confidence),
            }
            key = _article_key(enriched)
            if not key:
                continue

            existing = deduped.get(key)
            if not existing:
                deduped[key] = enriched
                continue

            neighborhoods = set(existing.get("verified_neighborhoods") or []) | {neighborhood}
            existing["verified_neighborhoods"] = sorted(neighborhoods)
            for field, value in (
                ("neighborhood_evidence", evidence),
                ("neighborhood_confidence", confidence),
                ("neighborhood_location_score", location_score),
            ):
                mapping = dict(existing.get(field) or {})
                mapping[neighborhood] = value
                existing[field] = mapping

    # Several candidates per neighborhood are useful because the selector can then
    # prefer a newer article without sacrificing geographic relevance or outlet quality.
    return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)[:240]
