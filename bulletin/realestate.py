from __future__ import annotations

import math
import os
import re
from datetime import date, timedelta
from typing import Any

import httpx

from .analysis import slugify
from .config import ANALYSIS_NEIGHBORHOODS

ATTOM_BASE_URL = os.getenv(
    "ATTOM_BASE_URL",
    "https://api.gateway.attomdata.com/propertyapi/v1.0.0",
).rstrip("/")
DATASF_BASE_URL = os.getenv("DATASF_BASE_URL", "https://data.sfgov.org/resource").rstrip("/")
SF_FIPS = "06075"
SF_CENTER = (37.7749, -122.4194)

RESIDENTIAL_INDICATORS = {10, 11, 21}
COMMERCIAL_INDICATORS = {20, 22, 23, 24, 25, 26, 27, 29, 30, 31, 32, 50, 51, 52, 53, 54}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _apn(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _boolish(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _property_group(summary: dict[str, Any]) -> str:
    indicator = int(_num(summary.get("propIndicator")))
    if indicator in RESIDENTIAL_INDICATORS:
        return "residential"
    if indicator in COMMERCIAL_INDICATORS:
        return "commercial"
    label = " ".join(
        str(summary.get(key) or "") for key in ("propertyType", "propclass", "proptype", "propsubType")
    ).lower()
    if any(word in label for word in ("single family", "condo", "townhouse", "duplex", "triplex", "quadplex", "residential")):
        return "residential"
    return "commercial"


def _sale_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    identifier = raw.get("identifier") or {}
    address = raw.get("address") or {}
    summary = raw.get("summary") or {}
    building = raw.get("building") or {}
    size = building.get("size") or {}
    sale = raw.get("sale") or {}
    amount = sale.get("amount") or {}
    calculation = sale.get("calculation") or {}

    if str(identifier.get("fips") or "") != SF_FIPS:
        return None

    sale_amount = _num(amount.get("saleamt"))
    if sale_amount < 100_000:
        return None
    if _boolish(sale.get("interfamily")):
        return None

    universal_size = _num(size.get("universalsize") or size.get("grosssizeadjusted") or size.get("bldgsize"))
    ppsf = _num(calculation.get("pricepersizeunit"))
    if not ppsf and universal_size > 0:
        ppsf = sale_amount / universal_size

    apn = _apn(identifier.get("apn"))
    apn_orig = _apn(identifier.get("apnOrig"))
    if not apn and not apn_orig:
        return None

    property_type = str(summary.get("proptype") or summary.get("propsubType") or summary.get("propertyType") or "Property")
    sale_date = str(sale.get("salesearchdate") or sale.get("saleTransDate") or amount.get("salerecdate") or "")[:10]

    return {
        "attom_id": identifier.get("attomId") or identifier.get("Id"),
        "apn": apn,
        "apn_orig": apn_orig,
        "address": str(address.get("oneLine") or address.get("line1") or "").strip(),
        "address_line": str(address.get("line1") or address.get("oneLine") or "").strip(),
        "zip": str(address.get("postal1") or "").strip(),
        "sale_date": sale_date,
        "recorded_date": str(amount.get("salerecdate") or "")[:10],
        "sale_price": round(sale_amount),
        "square_feet": round(universal_size) if universal_size > 0 else None,
        "price_per_sqft": round(ppsf) if ppsf > 0 else None,
        "property_type": property_type,
        "property_group": _property_group(summary),
        "units": int(_num((building.get("summary") or {}).get("unitsCount"))) or None,
        "year_built": int(_num(summary.get("yearbuilt"))) or None,
        "document_number": str(amount.get("saledocnum") or "").strip(),
        "transaction_type": str(amount.get("saletranstype") or "").strip(),
    }


def _score(item: dict[str, Any]) -> float:
    price = max(_num(item.get("sale_price")), 1)
    ppsf = max(_num(item.get("price_per_sqft")), 0)
    return math.log10(price) * 12 + min(ppsf / 150, 14)


class RealEstateClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("ATTOM_API_KEY", "").strip()
        self.lookback_days = _int_env("REALESTATE_LOOKBACK_DAYS", 45, 14, 120)
        self.max_pages = _int_env("REALESTATE_MAX_PAGES", 8, 1, 20)
        self.page_size = _int_env("REALESTATE_PAGE_SIZE", 100, 10, 100)
        self.timeout = 20.0
        self.datasf_token = os.getenv("DATASF_APP_TOKEN", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def _attom_sales(self, end: date) -> list[dict[str, Any]]:
        start = end - timedelta(days=self.lookback_days)
        headers = {"Accept": "application/json", "apikey": self.api_key}
        output: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            for page in range(1, self.max_pages + 1):
                params = {
                    "latitude": SF_CENTER[0],
                    "longitude": SF_CENTER[1],
                    "radius": 8,
                    "startSaleSearchDate": start.strftime("%Y/%m/%d"),
                    "endSaleSearchDate": end.strftime("%Y/%m/%d"),
                    "page": page,
                    "pageSize": self.page_size,
                    "orderBy": "SaleSearchDate desc",
                }
                response = await client.get(f"{ATTOM_BASE_URL}/sale/detail", params=params)
                response.raise_for_status()
                payload = response.json()
                raw_rows = payload.get("property") or []
                for raw in raw_rows:
                    parsed = _sale_record(raw)
                    if parsed:
                        output.append(parsed)
                status = payload.get("status") or {}
                total = int(_num(status.get("total")))
                page_size = int(_num(status.get("pagesize"))) or self.page_size
                if not raw_rows or page * page_size >= total:
                    break
        deduped: dict[tuple[str, str, int], dict[str, Any]] = {}
        for item in output:
            key = (item.get("apn") or item.get("apn_orig") or "", item.get("sale_date") or "", int(item.get("sale_price") or 0))
            deduped[key] = item
        return list(deduped.values())

    async def _neighborhood_map(self, sales: list[dict[str, Any]]) -> dict[str, str]:
        apns = sorted({x for item in sales for x in (item.get("apn"), item.get("apn_orig")) if x})
        if not apns:
            return {}
        headers = {"Accept": "application/json"}
        if self.datasf_token:
            headers["X-App-Token"] = self.datasf_token
        mapping: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
            for start in range(0, len(apns), 80):
                chunk = apns[start : start + 80]
                quoted = ",".join("'" + value.replace("'", "''") + "'" for value in chunk)
                params = {
                    "$select": "parcel_number,analysis_neighborhood",
                    "$where": f"parcel_number in({quoted})",
                    "$limit": 5000,
                }
                response = await client.get(f"{DATASF_BASE_URL}/9grn-xjpx.json", params=params)
                response.raise_for_status()
                for row in response.json():
                    parcel = _apn(row.get("parcel_number"))
                    hood = str(row.get("analysis_neighborhood") or "").strip()
                    if parcel and hood:
                        mapping[parcel] = hood
        return mapping

    async def fetch_recent(self, end: date) -> dict[str, Any]:
        empty_neighborhoods = {
            slugify(name): {"name": name, "residential": [], "commercial": [], "total": 0}
            for name in ANALYSIS_NEIGHBORHOODS
        }
        if not self.configured:
            return {
                "configured": False,
                "source": "ATTOM recorder-backed sales data",
                "lookback_days": self.lookback_days,
                "updated_at": None,
                "sales_count": 0,
                "neighborhoods": empty_neighborhoods,
                "city": {"largest": [], "largest_residential": [], "largest_commercial": [], "highest_ppsf": []},
            }

        sales = await self._attom_sales(end)
        mapping = await self._neighborhood_map(sales)
        neighborhoods = empty_neighborhoods
        matched: list[dict[str, Any]] = []

        for item in sales:
            hood = mapping.get(item.get("apn") or "") or mapping.get(item.get("apn_orig") or "")
            if not hood:
                continue
            slug = slugify(hood)
            if slug not in neighborhoods:
                neighborhoods[slug] = {"name": hood, "residential": [], "commercial": [], "total": 0}
            enriched = {**item, "neighborhood": hood, "slug": slug, "notable_score": round(_score(item), 1)}
            neighborhoods[slug][enriched["property_group"]].append(enriched)
            neighborhoods[slug]["total"] += 1
            matched.append(enriched)

        for data in neighborhoods.values():
            for group in ("residential", "commercial"):
                data[group].sort(key=lambda x: (x.get("notable_score", 0), x.get("sale_price", 0)), reverse=True)
                data[group] = data[group][:6]
            all_ppsf = [x.get("price_per_sqft") for x in data["residential"] + data["commercial"] if x.get("price_per_sqft")]
            data["median_visible_ppsf"] = round(sorted(all_ppsf)[len(all_ppsf) // 2]) if all_ppsf else None

        by_price = sorted(matched, key=lambda x: x.get("sale_price", 0), reverse=True)
        residential = [x for x in by_price if x.get("property_group") == "residential"]
        commercial = [x for x in by_price if x.get("property_group") == "commercial"]
        by_ppsf = sorted(
            [x for x in matched if x.get("price_per_sqft") and x.get("square_feet")],
            key=lambda x: x.get("price_per_sqft", 0),
            reverse=True,
        )
        return {
            "configured": True,
            "source": "ATTOM recorder-backed sales data",
            "source_note": "Sale price and property characteristics are recorder/assessor-backed fields supplied by ATTOM; neighborhood assignment uses DataSF parcel overlays.",
            "lookback_days": self.lookback_days,
            "updated_at": end.isoformat(),
            "sales_count": len(matched),
            "residential_count": len(residential),
            "commercial_count": len(commercial),
            "unmapped_count": max(0, len(sales) - len(matched)),
            "neighborhoods": neighborhoods,
            "city": {
                "largest": by_price[:12],
                "largest_residential": residential[:8],
                "largest_commercial": commercial[:8],
                "highest_ppsf": by_ppsf[:12],
            },
        }
