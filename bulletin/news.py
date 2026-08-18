from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx

from .config import ANALYSIS_NEIGHBORHOODS
from .curated_news import CURATED_NEWS


NEWS_QUERY_GROUPS = {
    "businesses": [
        '"San Francisco" restaurant retail business opening closing neighborhood when:21d',
        '"San Francisco" storefront vacancy lease small business corridor neighborhood when:30d',
    ],
    "permits": [
        '"San Francisco" housing development construction zoning neighborhood when:30d',
        '"San Francisco" redevelopment office conversion planning project neighborhood when:30d',
    ],
    "service_requests": [
        '"San Francisco" public works streets sidewalk park cleanup neighborhood when:21d',
        '"San Francisco" encampment graffiti sanitation roadwork neighborhood when:21d',
    ],
    "police": [
        '"San Francisco" shooting robbery burglary theft police neighborhood when:21d',
        '"San Francisco" arrest homicide vehicle theft public safety neighborhood when:21d',
    ],
}

# Restaurant reviews are intentionally stricter than general news matching. A review
# only appears in Happenings Near You when the Google News title/summary explicitly
# contains a controlled name for that Analysis Neighborhood. Search targeting alone
# is not accepted as proof that the restaurant is in the neighborhood.
RESTAURANT_NEIGHBORHOOD_TERMS: dict[str, tuple[str, ...]] = {
    "Bayview Hunters Point": ("Bayview Hunters Point", "Bayview", "Hunters Point"),
    "Bernal Heights": ("Bernal Heights",),
    "Castro/Upper Market": ("Castro", "Upper Market"),
    "Chinatown": ("Chinatown",),
    "Excelsior": ("Excelsior",),
    "Financial District/South Beach": ("Financial District", "South Beach"),
    "Glen Park": ("Glen Park",),
    "Golden Gate Park": ("Golden Gate Park",),
    "Haight Ashbury": ("Haight Ashbury", "Haight-Ashbury", "the Haight"),
    "Hayes Valley": ("Hayes Valley",),
    "Inner Richmond": ("Inner Richmond",),
    "Inner Sunset": ("Inner Sunset",),
    "Japantown": ("Japantown",),
    "Lakeshore": ("Lakeshore",),
    "Lincoln Park": ("Lincoln Park",),
    "Lone Mountain/USF": ("Lone Mountain",),
    "Marina": ("Marina District",),
    "McLaren Park": ("McLaren Park",),
    "Mission": ("Mission District", "the Mission"),
    "Mission Bay": ("Mission Bay",),
    "Nob Hill": ("Nob Hill",),
    "Noe Valley": ("Noe Valley",),
    "North Beach": ("North Beach",),
    "Oceanview/Merced/Ingleside": ("Oceanview", "Ingleside"),
    "Outer Mission": ("Outer Mission",),
    "Outer Richmond": ("Outer Richmond",),
    "Pacific Heights": ("Pacific Heights",),
    "Portola": ("Portola",),
    "Potrero Hill": ("Potrero Hill", "Dogpatch"),
    "Presidio": ("Presidio",),
    "Presidio Heights": ("Presidio Heights",),
    "Russian Hill": ("Russian Hill",),
    "Seacliff": ("Sea Cliff", "Seacliff"),
    "South of Market": ("South of Market", "SoMa"),
    "Sunset/Parkside": ("Parkside", "Outer Sunset"),
    "Tenderloin": ("Tenderloin",),
    "Treasure Island": ("Treasure Island",),
    "Twin Peaks": ("Twin Peaks",),
    "Visitacion Valley": ("Visitacion Valley",),
    "West of Twin Peaks": ("West of Twin Peaks",),
    "Western Addition": ("Western Addition", "Fillmore"),
}

RESTAURANT_REVIEW_LANGUAGE = re.compile(
    r"\b(review|reviewed|critic|restaurant critic|food critic|dining review|restaurant review|rated|rating)\b",
    re.I,
)
RESTAURANT_LANGUAGE = re.compile(r"\b(restaurant|dining|chef|menu|food|cafe|bistro|bar)\b", re.I)


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _contains_phrase(body: str, phrase: str) -> bool:
    normalized = _norm(phrase)
    return bool(normalized) and f" {normalized} " in f" {body} "


def _article_key(item: dict) -> str:
    title = str(item.get("title") or "")
    publisher = str(item.get("publisher") or "")
    if publisher and title.lower().endswith(" - " + publisher.lower()):
        title = title[: -(len(publisher) + 3)]
    return _norm(title)


def _story_for(edition: dict, key: str) -> dict:
    return next((story for story in edition.get("stories", []) if story.get("source") == key), {})


def _signal_priority(edition: dict, story: dict) -> float:
    key = story.get("source")
    metric = edition.get("metrics", {}).get(key, {})
    current = float(metric.get("current") or 0)
    baseline = float(metric.get("baseline_week") or 0)
    pct = abs(float(metric.get("pct_change") or 0))
    score = float(story.get("interest") or 0) + min(abs(current - baseline) * 2.5, 28) + min(pct / 5, 18)
    notable = edition.get("notable", {}).get(key, [])

    if key == "permits":
        housing = next((x for x in notable if (x.get("unit_delta") or 0) > 0), None)
        biggest_cost = max((float(x.get("cost") or 0) for x in notable), default=0)
        if housing:
            score += min(34, 12 + float(housing.get("unit_delta") or 0) * 3)
        if biggest_cost >= 1_000_000:
            score += min(24, 8 + len(str(int(biggest_cost))) * 2)
        if notable and all("minor alterations" in _norm(x.get("title")) for x in notable[:3]):
            score -= 18
    elif key == "businesses":
        if notable:
            score += 8
        if current < 2 and pct < 35:
            score -= 12
    elif key == "service_requests":
        categories = metric.get("categories") or []
        top = _norm(categories[0].get("display_category")) if categories else ""
        if any(term in top for term in ("graffiti", "street and sidewalk cleaning", "public works")) and pct < 60:
            score -= 22
        if current < 5:
            score -= 12
    elif key == "police":
        if current < 3:
            score -= 18
        if pct >= 40 and current >= 4:
            score += 10
    return score


def _target_query(edition: dict, story: dict) -> str:
    hood = edition.get("name") or "San Francisco"
    key = story.get("source")
    notable = edition.get("notable", {}).get(key, [])
    metric = edition.get("metrics", {}).get(key, {})

    if key == "businesses" and notable:
        name = str(notable[0].get("title") or "").strip()
        address = str(notable[0].get("address") or "").strip()
        anchor = f'"{name}"' if name and name.lower() != "new business" else f'"{hood}"'
        return f'{anchor} "San Francisco" {address} restaurant retail opening business when:45d'
    if key == "permits" and notable:
        project = notable[0]
        housing = next((x for x in notable if (x.get("unit_delta") or 0) > 0), None)
        project = housing or project
        address = str(project.get("address") or "").strip()
        desc = str(project.get("description") or "").strip()
        anchor = f'"{address}"' if address else f'"{hood}"'
        words = " ".join(desc.split()[:8])
        return f'{anchor} "San Francisco" housing development construction {words} when:60d'
    if key == "service_requests":
        categories = metric.get("categories") or []
        category = str(categories[0].get("display_category") or "city services") if categories else "city services"
        return f'"{hood}" "San Francisco" {category} streets public works neighborhood when:45d'
    if key == "police":
        categories = metric.get("categories") or []
        category = str(categories[0].get("display_category") or "police") if categories else "police"
        return f'"{hood}" "San Francisco" {category} police incident arrest neighborhood when:45d'
    return f'"{hood}" "San Francisco" neighborhood when:30d'


def _targeted_searches(snapshot: dict | None, limit: int = 12) -> list[tuple[str, str, str]]:
    if not snapshot:
        return []
    candidates: list[tuple[float, str, str, str]] = []
    for edition in snapshot.get("editions", {}).values():
        for story in edition.get("stories", []):
            score = _signal_priority(edition, story)
            if score < 48:
                continue
            key = str(story.get("source") or "")
            candidates.append((score, edition.get("name", ""), key, _target_query(edition, story)))
    candidates.sort(reverse=True)
    selected: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, hood, beat, query in candidates:
        pair = (hood, beat)
        if pair in seen:
            continue
        seen.add(pair)
        selected.append((beat, query, hood))
        if len(selected) >= limit:
            break
    return selected


def _restaurant_query(neighborhood: str) -> str:
    terms = RESTAURANT_NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
    # Use the least ambiguous preferred label as the search anchor. Validation below
    # still requires one of the controlled terms to occur in the result itself.
    anchor = terms[0]
    return f'"{anchor}" "San Francisco" restaurant review critic dining when:90d'


def _verified_review_neighborhoods(item: dict, target: str | None = None) -> tuple[list[str], dict[str, str]]:
    body = _norm((item.get("title") or "") + " " + (item.get("summary") or ""))
    candidates = [target] if target else list(ANALYSIS_NEIGHBORHOODS)
    verified: list[str] = []
    evidence: dict[str, str] = {}
    for neighborhood in candidates:
        if not neighborhood:
            continue
        terms = RESTAURANT_NEIGHBORHOOD_TERMS.get(neighborhood) or (neighborhood,)
        hit = next((term for term in terms if _contains_phrase(body, term)), None)
        if hit:
            verified.append(neighborhood)
            evidence[neighborhood] = hit
    return verified, evidence


class NewsContextClient:
    def __init__(self) -> None:
        self.timeout = 12.0
        self._semaphore = asyncio.Semaphore(6)

    async def _feed(self, beat: str, query: str, target_neighborhood: str | None = None) -> list[dict]:
        url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        headers = {"User-Agent": "sf-neighborhood-bulletin/1.1"}
        async with self._semaphore:
            async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        output: list[dict] = []
        for item in root.findall(".//item")[:14]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = item.findtext("description") or ""
            source_node = item.find("source")
            publisher = (source_node.text or "").strip() if source_node is not None else ""
            published_raw = (item.findtext("pubDate") or "").strip()
            try:
                published_dt = parsedate_to_datetime(published_raw)
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)
                published = published_dt.isoformat()
            except Exception:
                published = datetime.now(timezone.utc).isoformat()
            desc = re.sub(r"<[^>]+>", " ", html.unescape(desc))
            desc = " ".join(desc.split())
            if title and link:
                output.append(
                    {
                        "title": title,
                        "url": link,
                        "publisher": publisher or "Google News",
                        "published": published,
                        "beat": beat,
                        "neighborhoods": [],
                        "summary": desc[:360],
                        "live": True,
                        "target_neighborhoods": [target_neighborhood] if target_neighborhood else [],
                        "target_signal": beat if target_neighborhood else None,
                    }
                )
        return output

    async def fetch_recent(self, snapshot: dict | None = None) -> list[dict]:
        jobs: list[tuple[str, str, str | None]] = []
        for beat, queries in NEWS_QUERY_GROUPS.items():
            for query in queries:
                jobs.append((beat, query, None))
        for beat, query, hood in _targeted_searches(snapshot):
            jobs.append((beat, query, hood))

        fetched = await asyncio.gather(
            *(self._feed(beat, query, hood) for beat, query, hood in jobs),
            return_exceptions=True,
        )
        items = [dict(item, live=False, target_neighborhoods=item.get("neighborhoods") or []) for item in CURATED_NEWS]
        for result in fetched:
            if isinstance(result, BaseException):
                continue
            items.extend(result)

        deduped: dict[str, dict] = {}
        for item in items:
            key = _article_key(item)
            if not key:
                continue
            existing = deduped.get(key)
            if not existing:
                deduped[key] = item
                continue
            existing_targets = set(existing.get("target_neighborhoods") or [])
            new_targets = set(item.get("target_neighborhoods") or [])
            if new_targets - existing_targets:
                existing["target_neighborhoods"] = sorted(existing_targets | new_targets)
            if existing.get("live") and not item.get("live"):
                item["target_neighborhoods"] = sorted(existing_targets | new_targets)
                deduped[key] = item
        return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)

    async def fetch_restaurant_reviews(self) -> list[dict]:
        jobs = [(neighborhood, _restaurant_query(neighborhood)) for neighborhood in ANALYSIS_NEIGHBORHOODS]
        fetched = await asyncio.gather(
            *(self._feed("restaurant_reviews", query, neighborhood) for neighborhood, query in jobs),
            return_exceptions=True,
        )

        deduped: dict[str, dict] = {}
        for (neighborhood, _), result in zip(jobs, fetched):
            if isinstance(result, BaseException):
                continue
            for item in result:
                text = (item.get("title") or "") + " " + (item.get("summary") or "")
                if not RESTAURANT_LANGUAGE.search(text) or not RESTAURANT_REVIEW_LANGUAGE.search(text):
                    continue
                verified, evidence = _verified_review_neighborhoods(item, neighborhood)
                if neighborhood not in verified:
                    # A targeted search hit is not sufficient evidence. This is the rule
                    # that prevents a Santa Clara review from filling the Sea Cliff card.
                    continue
                item = {
                    **item,
                    "verified_neighborhoods": verified,
                    "neighborhood_evidence": evidence,
                    "review_verified": True,
                }
                key = _article_key(item)
                if not key:
                    continue
                existing = deduped.get(key)
                if not existing:
                    deduped[key] = item
                    continue
                neighborhoods = set(existing.get("verified_neighborhoods") or []) | set(verified)
                merged_evidence = dict(existing.get("neighborhood_evidence") or {})
                merged_evidence.update(evidence)
                existing["verified_neighborhoods"] = sorted(neighborhoods)
                existing["neighborhood_evidence"] = merged_evidence

        return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)[:80]
