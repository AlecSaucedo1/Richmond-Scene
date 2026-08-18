from __future__ import annotations

import asyncio
from typing import Any

from .config import ANALYSIS_NEIGHBORHOODS
from .neighborhood_coverage import location_confidence, publisher_score
from .news import RESTAURANT_LANGUAGE, RESTAURANT_NEIGHBORHOOD_TERMS, _article_key


def _query(neighborhood: str) -> str:
    terms = RESTAURANT_NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
    anchors = " OR ".join(f'"{term}"' for term in terms[:3])
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


def _enrich_for_neighborhood(item: dict, neighborhood: str) -> dict | None:
    text = (item.get("title") or "") + " " + (item.get("summary") or "")
    if not RESTAURANT_LANGUAGE.search(text):
        return None
    confidence, location_score, evidence = location_confidence(item, neighborhood)
    if not confidence:
        return None
    return {
        **item,
        "verified_neighborhoods": [neighborhood],
        "neighborhood_evidence": {neighborhood: evidence},
        "neighborhood_confidence": {neighborhood: confidence},
        "neighborhood_location_score": {neighborhood: location_score},
        "restaurant_verified": True,
        "review_verified": True,
        "restaurant_story_type": _story_type(item),
        "restaurant_source_score": publisher_score(item),
        "restaurant_confidence_score": _confidence_weight(confidence),
    }


def _merge_candidate(deduped: dict[str, dict], enriched: dict, neighborhood: str) -> None:
    key = _article_key(enriched)
    if not key:
        return
    existing = deduped.get(key)
    if not existing:
        deduped[key] = enriched
        return
    neighborhoods = set(existing.get("verified_neighborhoods") or []) | {neighborhood}
    existing["verified_neighborhoods"] = sorted(neighborhoods)
    for field in ("neighborhood_evidence", "neighborhood_confidence", "neighborhood_location_score"):
        mapping = dict(existing.get(field) or {})
        mapping.update(enriched.get(field) or {})
        existing[field] = mapping
    if len(str(enriched.get("summary") or "")) > len(str(existing.get("summary") or "")):
        existing["summary"] = enriched.get("summary")


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
            enriched = _enrich_for_neighborhood(item, neighborhood)
            if enriched:
                _merge_candidate(deduped, enriched, neighborhood)

    return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)[:240]


def merge_restaurant_news_candidates(restaurant_items: list[dict], news_items: list[dict]) -> list[dict]:
    """Merge dining-specific search results with restaurant stories found by local news.

    The general neighborhood search is often better at surfacing profiles, openings,
    closures and business stories that do not use restaurant-review vocabulary. Reuse
    those already location-checked articles rather than leaving the dining module empty.
    """
    deduped: dict[str, dict] = {}
    for item in restaurant_items:
        key = _article_key(item)
        if key:
            deduped[key] = dict(item)

    for item in news_items:
        neighborhoods = set(item.get("local_verified_neighborhoods") or []) | set(item.get("target_neighborhoods") or [])
        for neighborhood in neighborhoods:
            if neighborhood not in ANALYSIS_NEIGHBORHOODS:
                continue
            enriched = _enrich_for_neighborhood(item, neighborhood)
            if enriched:
                _merge_candidate(deduped, enriched, neighborhood)

    return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)[:300]
