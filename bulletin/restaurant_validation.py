from __future__ import annotations

import re
from typing import Any

from .config import ANALYSIS_NEIGHBORHOODS


OUTSIDE_SF_PLACES = (
    "santa clara",
    "san jose",
    "sunnyvale",
    "mountain view",
    "palo alto",
    "redwood city",
    "san mateo",
    "burlingame",
    "south san francisco",
    "daly city",
    "oakland",
    "berkeley",
    "emeryville",
    "alameda",
    "walnut creek",
    "san rafael",
    "sausalito",
    "mill valley",
    "napa",
    "sonoma",
)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _contains(body: str, phrase: str) -> bool:
    phrase = _norm(phrase)
    return bool(phrase) and f" {phrase} " in f" {body} "


def strict_verified_review_neighborhoods(item: dict, target: str | None = None) -> tuple[list[str], dict[str, str]]:
    # Imported lazily so this validator can be installed while the bulletin package
    # initializes without creating a circular module dependency.
    from .news import RESTAURANT_NEIGHBORHOOD_TERMS

    body = _norm((item.get("title") or "") + " " + (item.get("summary") or ""))
    if not body:
        return [], {}

    # If a result explicitly names another Bay Area city and does not also establish
    # San Francisco context, it cannot fill an SF neighborhood review slot.
    mentions_other_city = any(_contains(body, place) for place in OUTSIDE_SF_PLACES)
    if mentions_other_city and not _contains(body, "San Francisco"):
        return [], {}

    candidates = [target] if target else list(ANALYSIS_NEIGHBORHOODS)
    verified: list[str] = []
    evidence: dict[str, str] = {}
    for neighborhood in candidates:
        if not neighborhood:
            continue

        # Prevent a Presidio Heights review from being assigned to the Presidio simply
        # because the shorter word "Presidio" occurs inside the neighborhood name.
        if neighborhood == "Presidio" and _contains(body, "Presidio Heights") and not (
            _contains(body, "the Presidio") or _contains(body, "Presidio of San Francisco")
        ):
            continue

        terms = RESTAURANT_NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
        hit = next((term for term in terms if _contains(body, term)), None)
        if hit:
            verified.append(neighborhood)
            evidence[neighborhood] = hit

    return verified, evidence
