from __future__ import annotations

import asyncio
import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from bulletin.longread import build_long_read

PACIFIC = ZoneInfo("America/Los_Angeles")
RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-terra"

EDITORIAL_INSTRUCTIONS = """You are the senior neighborhood analyst for The San Francisco Bulletin.

Your job is not to summarize a list of metrics. Decide what matters, identify the most meaningful pattern, explain how different signals do or do not fit together, and give readers an intelligent view of what may matter next.

Write like a strong metropolitan newspaper analysis column: specific, skeptical, concrete, varied in structure, and willing to say when the evidence is contradictory or too thin.

FACT RULES
- Use only the supplied evidence. Do not browse or invent facts.
- Never turn temporal overlap into causation.
- A business registration is not proof that a storefront opened.
- A permit filing is not approval or completed construction.
- A DBI-listed owner is a permit-contact role, not title ownership.
- 311 is reported service demand plus reporting behavior, not a direct measure of conditions.
- SFPD reports filed are not a crime rate or a measure of neighborhood safety.
- A property transfer is not necessarily an arm's-length market sale.
- Journalism, dining, arts and real-estate records can add context but do not prove why another signal moved.
- Percent changes on small bases can be noisy. Use absolute counts, eight-week history and city rank.
- If signals conflict, explain the tension rather than smoothing it away.

ANALYTICAL EXPECTATIONS
1. Identify a central thesis unique to this neighborhood today.
2. Compare the latest seven-day window with the eight-week shape, not only the four-week average.
3. Use city rank and median to distinguish a local anomaly from a normal city-scale level.
4. Look for concentration by address, corridor, category, owner or contractor when supported.
5. Distinguish leading indicators from lagging indicators.
6. Decide whether the pattern looks persistent, emerging, reverting to normal, mixed, or mostly noise.
7. If yesterday's thesis is supplied, decide whether today's evidence strengthens it, weakens it, or changes the story.
8. The outlook must name observable developments that would strengthen or undermine the thesis.
9. Do not force every beat into the story. Leave out weak signals.
10. Vary the narrative architecture by neighborhood.

STYLE
- Avoid stock openings and fixed paragraph templates.
- Do not march through Business, Permits, 311 and Police in the same order.
- Prefer named projects, addresses, businesses, owners, contractors and corridors when supplied.
- Use restrained forward-looking language.
- Aim for 850-1,150 words when evidence is rich; be shorter when evidence is thin.
- Return valid JSON only.

RETURN THIS SHAPE
{
  "headline": "specific analytical headline",
  "dek": "1-2 sentence standfirst",
  "thesis": "one concise thesis",
  "thesis_status": "new|strengthened|weakened|changed|mixed",
  "body": ["paragraph", "paragraph"],
  "connections": [{"signal_a":"...","signal_b":"...","interpretation":"...","confidence":"high|medium|low"}],
  "outlook": "forward-looking paragraph grounded in observable future signals",
  "watchlist": [{"signal":"specific thing to watch","would_mean":"what it would imply"}],
  "signals_connected": ["..."],
  "confidence": "high|medium|low",
  "uncertainties": ["important limitation"]
}
"""

def _text(value: Any, limit: int = 500) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip(" ,;:-") + "…"

def _metric(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_7d": metric.get("current"),
        "baseline_week": metric.get("baseline_week"),
        "pct_change": metric.get("pct_change"),
        "latest_source_date": str(metric.get("latest") or "")[:10],
        "city_rank": metric.get("city_rank"),
        "city_neighborhoods": metric.get("city_total_neighborhoods"),
        "city_median": metric.get("city_median"),
        "eight_week_counts": list(metric.get("weekly_history") or [])[-8:],
        "top_categories": [{"name": x.get("display_category") or x.get("category"), "current": x.get("current"), "baseline": x.get("baseline"), "pct_change": x.get("pct_change")} for x in (metric.get("categories") or [])[:5]],
    }

def _record(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("title","address","description","scope_summary","category","status","status_summary","cost","permit_number","existing_units","proposed_units","unit_delta","existing_use","proposed_use","owner","general_contractor","reported_display","incident_number","filed_date")
    out: dict[str, Any] = {}
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            out[key] = _text(value, 350) if isinstance(value, str) else value
    return out
