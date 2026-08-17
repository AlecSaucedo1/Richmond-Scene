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


NEWS_QUERIES = {
    "businesses": '"San Francisco" business opening restaurant retail neighborhood when:14d',
    "permits": '"San Francisco" housing development zoning permit neighborhood when:14d',
    "service_requests": '"San Francisco" streets transit encampment park neighborhood when:14d',
    "police": '"San Francisco" crime police neighborhood when:14d',
}


class NewsContextClient:
    def __init__(self) -> None:
        self.timeout = 12.0

    async def _feed(self, beat: str, query: str) -> list[dict]:
        url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        headers = {"User-Agent": "sf-neighborhood-bulletin/0.5"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        output: list[dict] = []
        for item in root.findall(".//item")[:18]:
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
                        "summary": desc[:320],
                        "live": True,
                    }
                )
        return output

    async def fetch_recent(self) -> list[dict]:
        fetched = await asyncio.gather(
            *(self._feed(beat, query) for beat, query in NEWS_QUERIES.items()),
            return_exceptions=True,
        )
        items = [dict(item, live=False) for item in CURATED_NEWS]
        for result in fetched:
            if isinstance(result, BaseException):
                continue
            items.extend(result)

        deduped: dict[str, dict] = {}
        for item in items:
            key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
            if not key:
                continue
            existing = deduped.get(key)
            if not existing or (existing.get("live") and not item.get("live")):
                deduped[key] = item
        return sorted(deduped.values(), key=lambda x: x.get("published", ""), reverse=True)
