from __future__ import annotations

import asyncio
import html
import math
import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx

from .analysis import slugify
from .config import ANALYSIS_NEIGHBORHOODS

DATASF_BASE_URL = os.getenv("DATASF_BASE_URL", "https://data.sfgov.org/resource").rstrip("/")
SFGATE_HOME_SALES_URL = os.getenv(
    "SFGATE_HOME_SALES_URL",
    "https://www.sfgate.com/realestate/article/homes-sold-18156285.php",
)
TRD_SF_URL = os.getenv("TRD_SF_URL", "https://therealdeal.com/san-francisco/")
USER_AGENT = "sf-neighborhood-bulletin/0.9 (+public-data civic newspaper)"

ADDRESS_DATASET = "5mjj-njit"  # DataSF Addresses with parcel number
PARCEL_OVERLAY_DATASET = "9grn-xjpx"  # DataSF parcel -> Analysis Neighborhood

SALE_LINE = re.compile(
    r"(?P<address>\d{1,5}(?:-\d{1,5})?\s+[^,\n]{2,90}),\s*"
    r"(?P<date>\d{2}/\d{2}/\d{4}),\s*\$(?P<price>[\d,]+)"
    r"(?P<rest>[^\n]{0,260})",
    re.I,
)
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}(?:-\d{1,5})?\s+(?:[A-Z0-9][A-Za-z0-9.'’-]*\s+){0,6}"
    r"(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|"
    r"Way|Place|Pl\.?|Terrace|Ter\.?|Highway|Hwy\.?|Court|Ct\.?)\b",
    re.I,
)
PRICE_PATTERN = re.compile(r"\$(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s*(million|billion|m|b))?", re.I)
SQFT_PATTERN = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:square[- ]feet|square[- ]foot|sq\.?\s*ft\.?|sf)\b", re.I)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
DATE_PATTERN = re.compile(
    r"(?:closed\s+on|closing\s+on|sold\s+on|purchased\s+on|acquired\s+on|deal\s+closed\s+on|on)\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2})(?:,\s*(\d{4}))?",
    re.I,
)
SALE_VERBS = re.compile(r"\b(sold|bought|purchased|acquired|closed on|deal closed|traded|changed hands|fetch(?:ed|es))\b", re.I)

SUFFIXES = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD", "DRIVE": "DR",
    "LANE": "LN", "PLACE": "PL", "TERRACE": "TER", "HIGHWAY": "HWY", "COURT": "CT",
}


def _num(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _apn(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _score(item: dict[str, Any]) -> float:
    price = max(_num(item.get("sale_price")), 1)
    ppsf = max(_num(item.get("price_per_sqft")), 0)
    commercial_boost = 5 if item.get("property_group") == "commercial" else 0
    return math.log10(price) * 12 + min(ppsf / 150, 14) + commercial_boost


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(?:p|div|li|h1|h2|h3|section|article)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def _iso_us_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def _base_address(address: str) -> str:
    value = re.sub(r"\s+#.*$", "", address.strip(), flags=re.I)
    value = re.sub(r"\s+(?:APT|UNIT|STE|SUITE)\s+.*$", "", value, flags=re.I)
    value = re.sub(r"[^A-Za-z0-9\- ]+", " ", value).upper()
    parts = value.split()
    if parts and parts[-1] in SUFFIXES:
        parts[-1] = SUFFIXES[parts[-1]]
    return " ".join(parts)


def _residential_sales(raw_html: str) -> list[dict[str, Any]]:
    text = _html_to_text(raw_html)
    start = text.find("San Francisco County")
    end = text.find("San Mateo County", start + 1) if start >= 0 else -1
    if start < 0:
        raise RuntimeError("SFGATE San Francisco sales section was not found")
    section = text[start : end if end > start else len(text)]
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for match in SALE_LINE.finditer(section):
        address = match.group("address").strip()
        sale_date = _iso_us_date(match.group("date"))
        sale_price = int(_num(match.group("price")))
        rest = match.group("rest") or ""
        sqft_match = re.search(r"([\d,]+)\s*sf\b", rest, re.I)
        sqft = int(_num(sqft_match.group(1))) if sqft_match else None
        year_match = re.search(r"built\s+(\d{4})", rest, re.I)
        beds_match = re.search(r"([\d.]+)\s*bdrms?", rest, re.I)
        baths_match = re.search(r"([\d.]+)\s*bthrms?", rest, re.I)
        if sale_price < 100_000 or not sale_date:
            continue
        key = (_base_address(address), sale_date, sale_price)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "address": address,
                "address_line": address,
                "sale_date": sale_date,
                "recorded_date": sale_date,
                "sale_price": sale_price,
                "square_feet": sqft,
                "price_per_sqft": round(sale_price / sqft) if sqft else None,
                "property_type": "Residential",
                "property_group": "residential",
                "year_built": int(year_match.group(1)) if year_match else None,
                "bedrooms": _num(beds_match.group(1)) if beds_match else None,
                "bathrooms": _num(baths_match.group(1)) if baths_match else None,
                "source": "SFGATE Neighborhood Homes Sold",
                "source_url": SFGATE_HOME_SALES_URL,
                "source_kind": "county-record transaction listing",
            }
        )
    if not output:
        raise RuntimeError("No San Francisco residential sale records were parsed from SFGATE")
    return output


def _price_value(match: re.Match[str]) -> int:
    value = _num(match.group(1))
    suffix = (match.group(2) or "").lower()
    if suffix in {"million", "m"}:
        value *= 1_000_000
    elif suffix in {"billion", "b"}:
        value *= 1_000_000_000
    return round(value)


def _article_date_from_url(url: str) -> date | None:
    match = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _explicit_sale_date(context: str, article_date: date | None) -> str | None:
    match = DATE_PATTERN.search(context)
    if match:
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else (article_date.year if article_date else date.today().year)
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    if article_date:
        weekday = re.search(r"\blast\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", context, re.I)
        if weekday:
            targets = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            target = targets[weekday.group(1).lower()]
            days_back = (article_date.weekday() - target) % 7 or 7
            return (article_date - timedelta(days=days_back)).isoformat()
    return None


def _commercial_type(context: str) -> str:
    lower = context.lower()
    for needle, label in (
        ("hotel", "Hotel"), ("multifamily", "Multifamily"), ("apartment", "Multifamily"),
        ("industrial", "Industrial"), ("warehouse", "Industrial"), ("retail", "Retail"),
        ("office", "Office"), ("mixed-use", "Mixed-use"), ("mixed use", "Mixed-use"),
    ):
        if needle in lower:
            return label
    return "Commercial"


def _commercial_from_article(url: str, raw_html: str) -> dict[str, Any] | None:
    text = _html_to_text(raw_html)
    article_date = _article_date_from_url(url)
    title_match = re.search(r"(?is)<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)", raw_html)
    title = html.unescape(title_match.group(1)).strip() if title_match else "Commercial property sale"
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for index, sentence in enumerate(sentences):
        if not SALE_VERBS.search(sentence) or not PRICE_PATTERN.search(sentence):
            continue
        if re.search(r"\b(for sale|listed for sale|asking|hoping to sell)\b", sentence, re.I):
            continue
        context = " ".join(sentences[max(0, index - 2) : min(len(sentences), index + 2)])
        address_match = ADDRESS_PATTERN.search(context)
        price_match = PRICE_PATTERN.search(sentence)
        sale_date = _explicit_sale_date(context, article_date)
        if not address_match or not price_match or not sale_date:
            continue
        sale_price = _price_value(price_match)
        if sale_price < 500_000:
            continue
        sqft_matches = list(SQFT_PATTERN.finditer(context))
        sqft = None
        if sqft_matches:
            candidates = [int(_num(m.group(1))) for m in sqft_matches if _num(m.group(1)) >= 500]
            if candidates:
                sqft = min(candidates, key=lambda n: abs((sale_price / max(n, 1)) - 500))
        address = address_match.group(0).strip().rstrip(".,")
        return {
            "address": address,
            "address_line": address,
            "sale_date": sale_date,
            "recorded_date": sale_date,
            "sale_price": sale_price,
            "square_feet": sqft,
            "price_per_sqft": round(sale_price / sqft) if sqft else None,
            "property_type": _commercial_type(context),
            "property_group": "commercial",
            "source": "The Real Deal",
            "source_url": url,
            "source_title": title,
            "source_kind": "reported notable commercial transaction",
        }
    return None


class RealEstateClient:
    def __init__(self) -> None:
        self.timeout = 20.0
        self.datasf_token = os.getenv("DATASF_APP_TOKEN", "").strip()
        self.commercial_article_limit = max(4, min(24, int(os.getenv("REALESTATE_COMMERCIAL_ARTICLES", "14"))))

    @property
    def configured(self) -> bool:
        return True

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url)
        response.raise_for_status()
        return response.text

    async def _fetch_sales(self) -> tuple[list[dict[str, Any]], str | None]:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            home_html, trd_html = await asyncio.gather(
                self._get(client, SFGATE_HOME_SALES_URL),
                self._get(client, TRD_SF_URL),
            )
            residential = _residential_sales(home_html)
            modified = None
            meta = re.search(r"(?is)<meta[^>]+(?:property|name)=[\"']article:modified_time[\"'][^>]+content=[\"']([^\"']+)", home_html)
            if meta:
                modified = meta.group(1)

            hrefs = re.findall(r"href=[\"']([^\"']*/san-francisco/20\d{2}/\d{2}/\d{2}/[^\"'#?]+)", trd_html, re.I)
            urls: list[str] = []
            for href in hrefs:
                full = urljoin(TRD_SF_URL, href)
                if full not in urls:
                    urls.append(full)
                if len(urls) >= self.commercial_article_limit:
                    break
            pages = await asyncio.gather(*(self._get(client, url) for url in urls), return_exceptions=True)
            commercial: list[dict[str, Any]] = []
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

    async def _lookup_parcel(self, client: httpx.AsyncClient, address: str) -> str | None:
        base = _base_address(address)
        if not base:
            return None
        escaped = base.replace("'", "''")
        params = {
            "$select": "address,parcel_number",
            "$where": f"upper(address) like '{escaped}%'",
            "$limit": 8,
        }
        response = await client.get(f"{DATASF_BASE_URL}/{ADDRESS_DATASET}.json", params=params)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None
        # Prefer the shortest address match; it is usually the base parcel rather than a secondary address alias.
        rows.sort(key=lambda row: len(str(row.get("address") or "")))
        return _apn(rows[0].get("parcel_number")) or None

    async def _enrich_neighborhoods(self, sales: list[dict[str, Any]]) -> list[dict[str, Any]]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.datasf_token:
            headers["X-App-Token"] = self.datasf_token
        semaphore = asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            async def lookup(item: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
                async with semaphore:
                    try:
                        return item, await self._lookup_parcel(client, item.get("address") or "")
                    except Exception:
                        return item, None

            parcel_results = await asyncio.gather(*(lookup(item) for item in sales))
            apns = sorted({apn for _, apn in parcel_results if apn})
            mapping: dict[str, str] = {}
            for start in range(0, len(apns), 80):
                chunk = apns[start : start + 80]
                quoted = ",".join("'" + value.replace("'", "''") + "'" for value in chunk)
                params = {
                    "$select": "parcel_number,analysis_neighborhood",
                    "$where": f"parcel_number in({quoted})",
                    "$limit": 5000,
                }
                response = await client.get(f"{DATASF_BASE_URL}/{PARCEL_OVERLAY_DATASET}.json", params=params)
                response.raise_for_status()
                for row in response.json():
                    parcel = _apn(row.get("parcel_number"))
                    hood = str(row.get("analysis_neighborhood") or "").strip()
                    if parcel and hood:
                        mapping[parcel] = hood

        enriched: list[dict[str, Any]] = []
        for item, apn in parcel_results:
            hood = mapping.get(apn or "")
            if not hood:
                # Keep the transaction citywide even if the address-to-parcel join misses.
                enriched.append({**item, "apn": apn, "neighborhood": None, "slug": None, "notable_score": round(_score(item), 1)})
                continue
            enriched.append(
                {
                    **item,
                    "apn": apn,
                    "neighborhood": hood,
                    "slug": slugify(hood),
                    "notable_score": round(_score(item), 1),
                }
            )
        return enriched

    async def fetch_recent(self, end: date) -> dict[str, Any]:
        neighborhoods = {
            slugify(name): {"name": name, "residential": [], "commercial": [], "total": 0}
            for name in ANALYSIS_NEIGHBORHOODS
        }
        raw_sales, source_modified = await self._fetch_sales()
        sales = await self._enrich_neighborhoods(raw_sales)

        for item in sales:
            slug = item.get("slug")
            if not slug or slug not in neighborhoods:
                continue
            group = item.get("property_group") or "residential"
            neighborhoods[slug][group].append(item)
            neighborhoods[slug]["total"] += 1

        for data in neighborhoods.values():
            for group in ("residential", "commercial"):
                data[group].sort(key=lambda x: (x.get("notable_score", 0), x.get("sale_price", 0)), reverse=True)
                data[group] = data[group][:6]
            visible_ppsf = [
                x.get("price_per_sqft")
                for x in data["residential"] + data["commercial"]
                if x.get("price_per_sqft")
            ]
            data["median_visible_ppsf"] = (
                round(sorted(visible_ppsf)[len(visible_ppsf) // 2]) if visible_ppsf else None
            )

        by_price = sorted(sales, key=lambda x: x.get("sale_price", 0), reverse=True)
        residential = [x for x in by_price if x.get("property_group") == "residential"]
        commercial = [x for x in by_price if x.get("property_group") == "commercial"]
        by_ppsf = sorted(
            [x for x in sales if x.get("price_per_sqft") and x.get("square_feet")],
            key=lambda x: x.get("price_per_sqft", 0),
            reverse=True,
        )

        return {
            "configured": True,
            "source": "Free public web + DataSF",
            "source_note": (
                "Residential sale facts come from SFGATE's weekly Neighborhood Homes Sold listing, which says its "
                "address, price, date and property characteristics are based on Bay Area county transaction records "
                "supplied by California REsource. Notable commercial sales come from recent San Francisco real-estate "
                "reporting only when the article states a property location, transaction price and sale/closing date. "
                "DataSF address and parcel datasets assign transactions to Analysis Neighborhoods."
            ),
            "source_window": "Latest published residential transaction list + recent notable commercial closings",
            "updated_at": end.isoformat(),
            "source_modified_at": source_modified,
            "sales_count": len(sales),
            "residential_count": len(residential),
            "commercial_count": len(commercial),
            "mapped_count": sum(1 for x in sales if x.get("neighborhood")),
            "unmapped_count": sum(1 for x in sales if not x.get("neighborhood")),
            "neighborhoods": neighborhoods,
            "city": {
                "largest": by_price[:12],
                "largest_residential": residential[:8],
                "largest_commercial": commercial[:8],
                "highest_ppsf": by_ppsf[:12],
            },
        }
