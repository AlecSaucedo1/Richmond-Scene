from __future__ import annotations

import re
from typing import Any


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def select_restaurant_review(snapshot: dict, neighborhood: str) -> dict | None:
    """Return the newest useful restaurant story verified for this neighborhood.

    Despite the legacy function name, the eligible content is now broader than reviews:
    openings, closures, chef/menu stories, profiles and reviews can all qualify. Location
    verification remains strict so another neighborhood or Bay Area city can never fill
    the card. No verified match means no article rather than a geographic fallback.
    """
    candidates: list[tuple[int, str, dict]] = []
    for item in snapshot.get("restaurant_reviews") or []:
        if not (item.get("restaurant_verified") or item.get("review_verified")):
            continue
        verified = set(item.get("verified_neighborhoods") or [])
        if neighborhood not in verified:
            continue

        evidence = (item.get("neighborhood_evidence") or {}).get(neighborhood, neighborhood)
        title = _norm(item.get("title"))
        score = 20
        if _norm(evidence) and f" {_norm(evidence)} " in f" {title} ":
            score += 8
        publisher = _norm(item.get("publisher"))
        if any(name in publisher for name in (
            "san francisco chronicle",
            "eater",
            "sf standard",
            "infatuation",
            "mission local",
            "kqed",
        )):
            score += 3
        candidates.append((score, str(item.get("published") or ""), item))

    if not candidates:
        return None

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = candidates[0][2]
    evidence = (best.get("neighborhood_evidence") or {}).get(neighborhood, neighborhood)
    return {
        **best,
        "match": f"{best.get('restaurant_story_type') or 'Neighborhood dining'} · verified for {neighborhood}",
        "location_evidence": evidence,
    }
