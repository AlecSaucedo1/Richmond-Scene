from __future__ import annotations

from typing import Any

from .config import ANALYSIS_NEIGHBORHOODS
from .news import RESTAURANT_LANGUAGE, RESTAURANT_NEIGHBORHOOD_TERMS, _article_key
from .restaurant_validation import strict_verified_review_neighborhoods


def _query(neighborhood: str) -> str:
    terms = RESTAURANT_NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
    anchor = terms[0]
    # Broader than a review-only query: openings, closures, chef/menu changes,
    # profiles and dining reviews all add useful neighborhood texture.
    return (
        f'"{anchor}" "San Francisco" '
        'restaurant cafe dining chef menu opening opens closing closes review food when:180d'
    )


def _story_type(item: dict[str, Any]) -> str:
    body = ((item.get("title") or "") + " " + (item.get("summary") or "")).lower()
    if any(term in body for term in ("review", "critic", "rated", "rating")):
        return "Restaurant review"
    if any(term in body for term in ("close", "closing", "shutter")):
        return "Restaurant closure"
    if any(term in body for term in ("open", "opening", "debut", "launch")):
        return "Restaurant opening"
    if any(term in body for term in ("chef", "menu", "owner", "ownership")):
        return "Restaurant news"
    return "Neighborhood dining"


async def fetch_neighborhood_restaurant_news(client) -> list[dict]:
    jobs = [(neighborhood, _query(neighborhood)) for neighborhood in ANALYSIS_NEIGHBORHOODS]
    fetched = await __import__("asyncio").gather(
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

            verified, evidence = strict_verified_review_neighborhoods(item, neighborhood)
            if neighborhood not in verified:
                continue

            enriched = {
                **item,
                "verified_neighborhoods": verified,
                "neighborhood_evidence": evidence,
                "restaurant_verified": True,
                # Keep this legacy flag while older cached clients transition.
                "review_verified": True,
                "restaurant_story_type": _story_type(item),
            }
            key = _article_key(enriched)
            if not key:
                continue

            existing = deduped.get(key)
            if not existing:
                deduped[key] = enriched
                continue

            neighborhoods = set(existing.get("verified_neighborhoods") or []) | set(verified)
            merged_evidence = dict(existing.get("neighborhood_evidence") or {})
            merged_evidence.update(evidence)
            existing["verified_neighborhoods"] = sorted(neighborhoods)
            existing["neighborhood_evidence"] = merged_evidence

    # Enough headroom for all 41 neighborhoods to retain several candidates while
    # still keeping the serialized snapshot compact.
    return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)[:160]
