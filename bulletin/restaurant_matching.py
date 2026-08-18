from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .neighborhood_coverage import publisher_score


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _published(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _recency(age_days: int) -> int:
    if age_days <= 7:
        return 52
    if age_days <= 30:
        return 42
    if age_days <= 90:
        return 31
    if age_days <= 180:
        return 21
    if age_days <= 270:
        return 13
    if age_days <= 365:
        return 7
    return -30


def _confidence(item: dict, neighborhood: str) -> tuple[str, int]:
    confidence = (item.get("neighborhood_confidence") or {}).get(neighborhood)
    if not confidence:
        # Older snapshots used explicit verification only.
        confidence = "explicit" if neighborhood in set(item.get("verified_neighborhoods") or []) else ""
    weight = {
        "explicit": 42,
        "targeted_notable": 29,
        "targeted_sf": 22,
        "targeted_search": 12,
    }.get(confidence, 0)
    return confidence, weight


def select_restaurant_review(snapshot: dict, neighborhood: str) -> dict | None:
    """Return the strongest recent restaurant story for a neighborhood.

    Newer reporting receives the largest ranking bonus, but older credible local
    coverage remains eligible for up to a year so quiet editions are not left empty.
    Geographic confidence and publisher quality are scored separately from recency.
    """
    now = datetime.now(timezone.utc)
    candidates: list[tuple[float, datetime, dict]] = []
    for item in snapshot.get("restaurant_reviews") or []:
        if not (item.get("restaurant_verified") or item.get("review_verified")):
            continue
        if neighborhood not in set(item.get("verified_neighborhoods") or []):
            continue

        published = _published(item.get("published"))
        age_days = max(0, (now - published).days)
        if age_days > 365:
            continue

        confidence, confidence_score = _confidence(item, neighborhood)
        if not confidence_score:
            continue
        evidence = (item.get("neighborhood_evidence") or {}).get(neighborhood, neighborhood)
        title = _norm(item.get("title"))
        score = float(confidence_score + publisher_score(item) + _recency(age_days))
        if _norm(evidence) and f" {_norm(evidence)} " in f" {title} ":
            score += 9
        story_type = item.get("restaurant_story_type") or "Neighborhood dining"
        if story_type in {"Restaurant opening", "Restaurant closure", "Restaurant review"}:
            score += 5

        candidates.append((score, published, {
            **item,
            "restaurant_rank": round(score, 1),
            "restaurant_age_days": age_days,
            "location_evidence": evidence,
            "match": f"{story_type} · {neighborhood}",
        }))

    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return candidates[0][2]
