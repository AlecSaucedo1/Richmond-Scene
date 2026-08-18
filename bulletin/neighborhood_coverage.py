from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from .config import ANALYSIS_NEIGHBORHOODS


# Analysis Neighborhood names do not always match the names local reporters use.
# These aliases stay neighborhood-specific enough to avoid turning a citywide search
# into a geographic guess, while improving recall for common local names.
NEIGHBORHOOD_TERMS: dict[str, tuple[str, ...]] = {
    "Bayview Hunters Point": ("Bayview Hunters Point", "Bayview", "Hunters Point", "India Basin"),
    "Bernal Heights": ("Bernal Heights",),
    "Castro/Upper Market": ("Castro", "Upper Market", "Castro District"),
    "Chinatown": ("San Francisco Chinatown", "Chinatown"),
    "Excelsior": ("Excelsior District", "Excelsior"),
    "Financial District/South Beach": ("Financial District", "FiDi", "South Beach", "East Cut"),
    "Glen Park": ("Glen Park",),
    "Golden Gate Park": ("Golden Gate Park",),
    "Haight Ashbury": ("Haight-Ashbury", "Haight Ashbury", "Upper Haight", "the Haight"),
    "Hayes Valley": ("Hayes Valley",),
    "Inner Richmond": ("Inner Richmond",),
    "Inner Sunset": ("Inner Sunset",),
    "Japantown": ("San Francisco Japantown", "Japantown"),
    "Lakeshore": ("Lakeshore", "Stonestown", "Lakeside"),
    "Lincoln Park": ("Lincoln Park San Francisco", "Lincoln Park"),
    "Lone Mountain/USF": ("Lone Mountain", "University of San Francisco", "USF neighborhood"),
    "Marina": ("Marina District", "San Francisco Marina"),
    "McLaren Park": ("McLaren Park", "John McLaren Park"),
    "Mission": ("Mission District", "the Mission"),
    "Mission Bay": ("Mission Bay",),
    "Nob Hill": ("Nob Hill",),
    "Noe Valley": ("Noe Valley",),
    "North Beach": ("North Beach San Francisco", "North Beach"),
    "Oceanview/Merced/Ingleside": ("Oceanview", "Ingleside", "OMI", "Ocean View Merced Heights Ingleside"),
    "Outer Mission": ("Outer Mission",),
    "Outer Richmond": ("Outer Richmond",),
    "Pacific Heights": ("Pacific Heights",),
    "Portola": ("Portola District", "Portola"),
    "Potrero Hill": ("Potrero Hill", "Dogpatch"),
    "Presidio": ("the Presidio", "Presidio of San Francisco", "Presidio Tunnel Tops"),
    "Presidio Heights": ("Presidio Heights",),
    "Russian Hill": ("Russian Hill",),
    "Seacliff": ("Sea Cliff", "Seacliff"),
    "South of Market": ("South of Market", "SoMa"),
    "Sunset/Parkside": ("Outer Sunset", "Parkside", "Sunset District"),
    "Tenderloin": ("Tenderloin",),
    "Treasure Island": ("Treasure Island San Francisco", "Treasure Island"),
    "Twin Peaks": ("Twin Peaks San Francisco", "Twin Peaks"),
    "Visitacion Valley": ("Visitacion Valley",),
    "West of Twin Peaks": ("West of Twin Peaks", "Forest Hill", "Forest Knolls", "Miraloma Park"),
    "Western Addition": ("Western Addition", "Fillmore District", "Alamo Square", "NoPa"),
}

OUTSIDE_SF_PLACES = (
    "santa clara", "san jose", "sunnyvale", "mountain view", "palo alto", "redwood city",
    "san mateo", "burlingame", "south san francisco", "daly city", "oakland", "berkeley",
    "emeryville", "alameda", "walnut creek", "san rafael", "sausalito", "mill valley",
    "napa", "sonoma", "carmel", "sacramento", "los gatos", "menlo park", "albany",
)

NOTABLE_PUBLISHERS: tuple[tuple[str, int], ...] = (
    ("san francisco chronicle", 24),
    ("kqed", 23),
    ("sf standard", 22),
    ("mission local", 21),
    ("eater", 20),
    ("san francisco examiner", 19),
    ("sfist", 17),
    ("ingleside light", 17),
    ("richmond review", 17),
    ("sunset beacon", 17),
    ("potrero view", 17),
    ("marina times", 16),
    ("48 hills", 14),
    ("abc7", 13),
    ("nbc bay area", 13),
    ("cbs bay area", 13),
    ("ktvu", 13),
    ("kron4", 12),
    ("hoodline", 10),
)

SIGNIFICANCE_TERMS = re.compile(
    r"\b(open|opens|opening|close|closes|closing|shutter|housing|development|rezon|transit|muni|"
    r"school|park|fire|shoot|robbery|burglary|arrest|lawsuit|business|storefront|restaurant|"
    r"construction|permit|election|supervisor|mayor|street|project|historic|landmark|funding|grant)\w*\b",
    re.I,
)
RESTAURANT_TERMS = re.compile(r"\b(restaurant|cafe|dining|chef|menu|bar|bakery|bistro|food)\b", re.I)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _contains(body: str, phrase: str) -> bool:
    token = _norm(phrase)
    return bool(token) and f" {token} " in f" {body} "


def _published(item: dict) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(item.get("published") or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc) - timedelta(days=365)


def _article_key(item: dict) -> str:
    title = str(item.get("title") or "")
    publisher = str(item.get("publisher") or "")
    if publisher and title.lower().endswith(" - " + publisher.lower()):
        title = title[: -(len(publisher) + 3)]
    return _norm(title)


def publisher_score(item: dict) -> int:
    publisher = _norm(item.get("publisher"))
    return next((score for name, score in NOTABLE_PUBLISHERS if name in publisher), 4 if publisher else 0)


def is_notable_publisher(item: dict) -> bool:
    return publisher_score(item) >= 12


def _explicit_neighborhoods(body: str) -> set[str]:
    hits: set[str] = set()
    for neighborhood in ANALYSIS_NEIGHBORHOODS:
        terms = NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
        if any(_contains(body, term) for term in terms):
            hits.add(neighborhood)
    # The shorter words Mission and Presidio must not steal articles that clearly
    # identify Mission Bay or Presidio Heights.
    if "Mission Bay" in hits:
        hits.discard("Mission")
    if "Presidio Heights" in hits:
        hits.discard("Presidio")
    return hits


def location_confidence(item: dict, target: str) -> tuple[str | None, int, str]:
    body = _norm((item.get("title") or "") + " " + (item.get("summary") or ""))
    if not body:
        return None, 0, ""

    other_city = next((place for place in OUTSIDE_SF_PLACES if _contains(body, place)), None)
    if other_city and not _contains(body, "San Francisco"):
        return None, 0, ""

    explicit = _explicit_neighborhoods(body)
    if target in explicit:
        terms = NEIGHBORHOOD_TERMS.get(target) or (target,)
        evidence = next((term for term in terms if _contains(body, term)), target)
        return "explicit", 42, evidence
    if explicit and target not in explicit:
        return None, 0, ""

    targeted = target in (item.get("target_neighborhoods") or []) or target == item.get("local_search_target")
    if not targeted:
        return None, 0, ""

    if is_notable_publisher(item):
        return "targeted_notable", 27, "targeted neighborhood search from a notable local outlet"
    if _contains(body, "San Francisco"):
        return "targeted_sf", 20, "targeted neighborhood search with San Francisco context"
    return "targeted_search", 12, "targeted neighborhood search"


def _query(neighborhood: str) -> str:
    terms = NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
    quoted = " OR ".join(f'"{term}"' for term in terms[:4])
    return f'({quoted}) "San Francisco" when:330d'


async def fetch_neighborhood_news(client) -> list[dict]:
    jobs = [(neighborhood, _query(neighborhood)) for neighborhood in ANALYSIS_NEIGHBORHOODS]
    results = await asyncio.gather(
        *(client._feed("local", query, neighborhood) for neighborhood, query in jobs),
        return_exceptions=True,
    )

    deduped: dict[str, dict] = {}
    for (neighborhood, _), result in zip(jobs, results):
        if isinstance(result, BaseException):
            continue
        for item in result:
            enriched = {**item, "local_search_target": neighborhood}
            confidence, score, evidence = location_confidence(enriched, neighborhood)
            if not confidence:
                continue
            enriched["local_verified_neighborhoods"] = [neighborhood]
            enriched["local_location_confidence"] = {neighborhood: confidence}
            enriched["local_location_evidence"] = {neighborhood: evidence}
            enriched["local_location_score"] = {neighborhood: score}
            key = _article_key(enriched)
            if not key:
                continue
            existing = deduped.get(key)
            if not existing:
                deduped[key] = enriched
                continue
            verified = set(existing.get("local_verified_neighborhoods") or []) | {neighborhood}
            existing["local_verified_neighborhoods"] = sorted(verified)
            for field, value in (
                ("local_location_confidence", confidence),
                ("local_location_evidence", evidence),
                ("local_location_score", score),
            ):
                mapping = dict(existing.get(field) or {})
                mapping[neighborhood] = value
                existing[field] = mapping
    return sorted(deduped.values(), key=lambda item: item.get("published", ""), reverse=True)[:520]


def merge_news(base_items: list[dict], neighborhood_items: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in [*base_items, *neighborhood_items]:
        key = _article_key(item)
        if not key:
            continue
        existing = merged.get(key)
        if not existing:
            merged[key] = dict(item)
            continue
        for field in ("target_neighborhoods", "local_verified_neighborhoods"):
            values = set(existing.get(field) or []) | set(item.get(field) or [])
            if values:
                existing[field] = sorted(values)
        for field in ("local_location_confidence", "local_location_evidence", "local_location_score"):
            values = dict(existing.get(field) or {})
            values.update(item.get(field) or {})
            if values:
                existing[field] = values
        # Prefer richer summaries while preserving the original article URL/publisher.
        if len(str(item.get("summary") or "")) > len(str(existing.get("summary") or "")):
            existing["summary"] = item.get("summary")
    return sorted(merged.values(), key=lambda item: item.get("published", ""), reverse=True)


def _recency_score(age_days: int) -> float:
    if age_days <= 7:
        return 42
    if age_days <= 30:
        return 33
    if age_days <= 90:
        return 24
    if age_days <= 180:
        return 15
    if age_days <= 270:
        return 9
    if age_days <= 365:
        return 4
    return -20


def rank_neighborhood_articles(items: list[dict], neighborhood: str, now: datetime) -> list[dict]:
    ranked: list[tuple[float, datetime, dict]] = []
    for item in items:
        confidence, location_score, evidence = location_confidence(item, neighborhood)
        if not confidence:
            continue
        published = _published(item)
        age_days = max(0, (now - published).days)
        if age_days > 365:
            continue
        text = (item.get("title") or "") + " " + (item.get("summary") or "")
        score = float(location_score + publisher_score(item)) + _recency_score(age_days)
        if SIGNIFICANCE_TERMS.search(text):
            score += 7
        # Dining has its own section; keep it eligible but prefer broader neighborhood
        # reporting for the general news module when other stories exist.
        if RESTAURANT_TERMS.search(text):
            score -= 5
        if confidence == "explicit" and any(
            _contains(_norm(item.get("title")), term) for term in (NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,))
        ):
            score += 7
        reason = (
            f"Recent reporting about {neighborhood}; location matched by {evidence}."
            if confidence == "explicit"
            else f"Recent reporting surfaced by a targeted {neighborhood} search; included as neighborhood context, not as proof of the current data trend."
        )
        ranked.append((score, published, {
            **item,
            "match_reason": reason,
            "match_score": round(score, 1),
            "context_only": True,
            "neighborhood_match_confidence": confidence,
        }))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in ranked]


def backfill_neighborhood_coverage(snapshot: dict, items: list[dict], now: datetime) -> dict:
    usage = Counter()
    for edition in snapshot.get("editions", {}).values():
        for item in (edition.get("editorial") or {}).get("coverage", []):
            key = _article_key(item)
            if key:
                usage[key] += 1

    # Fill the strongest existing gaps first, but every edition gets the same chance
    # at local context. A fallback article is globally unique whenever possible.
    editions = list(snapshot.get("editions", {}).values())
    editions.sort(key=lambda edition: len((edition.get("editorial") or {}).get("coverage", [])))
    added = 0
    filled = 0
    for edition in editions:
        editorial = edition.setdefault("editorial", {})
        existing = list(editorial.get("coverage") or [])
        existing_keys = {_article_key(item) for item in existing}
        candidates = rank_neighborhood_articles(items, edition.get("name", ""), now)
        target_count = 3 if existing else 2
        for item in candidates:
            key = _article_key(item)
            if not key or key in existing_keys:
                continue
            if usage[key] >= 1:
                continue
            existing.append(item)
            existing_keys.add(key)
            usage[key] += 1
            added += 1
            if len(existing) >= target_count:
                break
        # If uniqueness alone would leave an edition empty, allow one reuse rather
        # than display an empty section. This is intentionally a last resort.
        if not existing:
            for item in candidates:
                key = _article_key(item)
                if not key or key in existing_keys or usage[key] >= 2:
                    continue
                existing.append(item)
                usage[key] += 1
                added += 1
                break
        editorial["coverage"] = existing[:3]
        edition["local_reporting"] = existing[:3]
        if existing:
            filled += 1

    context = snapshot.setdefault("news_context", {})
    context["neighborhood_backfill_articles"] = added
    context["neighborhoods_with_reporting"] = filled
    context["neighborhood_reporting_horizon_days"] = 365
    return snapshot
