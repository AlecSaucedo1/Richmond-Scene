from __future__ import annotations

import re
from typing import Any


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def select_restaurant_review(snapshot: dict, neighborhood: str) -> dict | None:
    """Return only a review explicitly verified for the requested neighborhood.

    The news client writes verified_neighborhoods only after the article title/summary
    contains a controlled neighborhood name. Targeted Google News search placement is
    never treated as location proof. If no review clears that check, return None rather
    than filling the card with an unrelated San Francisco or Bay Area restaurant.
    """
    candidates: list[tuple[int, str, dict]] = []
    for item in snapshot.get("restaurant_reviews") or []:
        if not item.get("review_verified"):
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
        "match": f"Verified for {neighborhood} · article names {evidence}",
    }
