from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx

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

RESTAURANT_REVIEW_QUERY = '"San Francisco" restaurant review critic dining when:30d'


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


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
        headers = {"User-Agent": "sf-neighborhood-bulletin/1.0"}
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
        items = await self._feed("restaurant_reviews", RESTAURANT_REVIEW_QUERY)
        review_terms = re.compile(r"\b(review|critic|restaurant|dining|chef|menu|food)\b", re.I)
        filtered = [
            item
            for item in items
            if review_terms.search((item.get("title") or "") + " " + (item.get("summary") or ""))
        ]
        deduped: dict[str, dict] = {}
        for item in filtered:
            key = _article_key(item)
            if key and key not in deduped:
                deduped[key] = item
        return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)[:20]
