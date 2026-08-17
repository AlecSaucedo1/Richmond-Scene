from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

import httpx

from .realestate import (
    SFGATE_HOME_SALES_URL,
    TRD_SF_URL,
    USER_AGENT,
    RealEstateClient as BaseRealEstateClient,
    _base_address,
    _commercial_from_article,
    _residential_sales,
)


class RealEstateClient(BaseRealEstateClient):
    """Free real-estate client with residential data as the required core feed.

    Commercial-sale reporting is useful enrichment, but it must never prevent the
    county-record-derived residential transaction list from publishing.
    """

    async def _fetch_sales(self):
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            home_html = await self._get(client, SFGATE_HOME_SALES_URL)
            residential = _residential_sales(home_html)

            modified = None
            meta = re.search(
                r"(?is)<meta[^>]+(?:property|name)=[\"']article:modified_time[\"'][^>]+content=[\"']([^\"']+)",
                home_html,
            )
            if meta:
                modified = meta.group(1)

            try:
                trd_html = await self._get(client, TRD_SF_URL)
            except Exception:
                return residential, modified

            hrefs = re.findall(
                r"href=[\"']([^\"']*/san-francisco/20\d{2}/\d{2}/\d{2}/[^\"'#?]+)",
                trd_html,
                re.I,
            )
            urls: list[str] = []
            for href in hrefs:
                full = urljoin(TRD_SF_URL, href)
                if full not in urls:
                    urls.append(full)
                if len(urls) >= self.commercial_article_limit:
                    break

            pages = await asyncio.gather(
                *(self._get(client, url) for url in urls),
                return_exceptions=True,
            )
            commercial = []
            seen: set[tuple[str, str, int]] = set()
            for url, raw in zip(urls, pages):
                if isinstance(raw, BaseException):
                    continue
                item = _commercial_from_article(url, raw)
                if not item:
                    continue
                key = (_base_address(item["address"]), item["sale_date"], item["sale_price"])
                if key in seen:
                    continue
                seen.add(key)
                commercial.append(item)

            return residential + commercial, modified
