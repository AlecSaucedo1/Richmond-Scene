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
  "sections": [{"heading":"model-chosen section heading","paragraphs":["paragraph","paragraph"]}],
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

def _trend_features(history: list[Any]) -> dict[str, Any]:
    values = []
    for value in history[-8:]:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            pass
    if not values:
        return {"shape": "no history"}
    recent = values[-3:]
    earlier = values[-6:-3] if len(values) >= 6 else values[:-3]
    recent_avg = sum(recent) / len(recent)
    earlier_avg = sum(earlier) / len(earlier) if earlier else recent_avg
    delta = recent_avg - earlier_avg
    spread = max(values) - min(values)
    mean = sum(values) / len(values)
    volatility = (spread / mean) if mean else 0.0
    if abs(delta) < max(0.5, mean * 0.08):
        shape = "roughly flat"
    elif delta > 0:
        shape = "rising over the recent three-week window"
    else:
        shape = "falling over the recent three-week window"
    return {
        "shape": shape,
        "recent_3wk_avg": round(recent_avg, 2),
        "prior_3wk_avg": round(earlier_avg, 2),
        "recent_minus_prior": round(delta, 2),
        "eight_week_min": min(values),
        "eight_week_max": max(values),
        "volatility_ratio": round(volatility, 2),
    }


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
        "trend_features": _trend_features(list(metric.get("weekly_history") or [])),
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

def _news_context(edition: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "title": _text(x.get("title"), 220),
        "publisher": _text(x.get("publisher"), 90),
        "published": x.get("published"),
        "summary": _text(x.get("summary"), 420),
        "match_reason": _text(x.get("match_reason"), 260),
        "context_only": bool(x.get("context_only")),
    } for x in ((edition.get("editorial") or {}).get("coverage") or [])[:5]]

def _real_estate(snapshot: dict[str, Any], slug: str) -> dict[str, Any]:
    desk = ((snapshot.get("real_estate") or {}).get("neighborhoods") or {}).get(slug) or {}
    def rows(key: str) -> list[dict[str, Any]]:
        return [{
            "address": x.get("address_line") or x.get("address"),
            "sale_price": x.get("sale_price"),
            "price_per_sqft": x.get("price_per_sqft"),
            "sale_date": x.get("sale_date"),
            "property_type": x.get("property_type"),
        } for x in (desk.get(key) or [])[:4]]
    return {"residential": rows("residential"), "commercial": rows("commercial")}

def _arts(snapshot: dict[str, Any], neighborhood: str) -> dict[str, Any]:
    desk = ((snapshot.get("arts") or {}).get("neighborhoods") or {}).get(neighborhood) or {}
    return {
        "exhibitions": [{"title":_text(x.get("title"),180),"museum":x.get("museum"),"start_date":x.get("start_date"),"end_date":x.get("end_date"),"summary":_text(x.get("summary"),320)} for x in (desk.get("exhibitions") or [])[:3]],
        "events": [{"title":_text(x.get("title"),180),"venue":x.get("venue"),"category":x.get("category"),"start_date":x.get("start_date"),"summary":_text(x.get("summary"),320)} for x in (desk.get("events") or [])[:3]],
    }

def _dining(snapshot: dict[str, Any], neighborhood: str) -> list[dict[str, Any]]:
    rows = []
    for x in snapshot.get("restaurant_reviews") or []:
        if neighborhood not in (x.get("verified_neighborhoods") or []):
            continue
        rows.append({"title":_text(x.get("title"),200),"publisher":_text(x.get("publisher"),90),"published":x.get("published"),"summary":_text(x.get("summary"),360),"story_type":x.get("restaurant_story_type")})
    rows.sort(key=lambda x: str(x.get("published") or ""), reverse=True)
    return rows[:3]

def _previous_analysis(previous_snapshot: dict[str, Any] | None, slug: str) -> dict[str, Any]:
    item = (((previous_snapshot or {}).get("long_reads") or {}).get(slug) or {})
    return {
        "generated_for": item.get("generated_for"),
        "headline": _text(item.get("headline"), 200),
        "thesis": _text(item.get("thesis"), 420),
        "thesis_status": item.get("thesis_status"),
        "outlook": _text(item.get("outlook"), 650),
        "watchlist": (item.get("watchlist") or [])[:5],
    }

def evidence_packet(snapshot: dict[str, Any], slug: str, edition: dict[str, Any], previous_snapshot: dict[str, Any] | None, day: str) -> dict[str, Any]:
    metrics = edition.get("metrics") or {}
    notable = edition.get("notable") or {}
    participants = edition.get("permit_market_participants") or {}
    editorial = edition.get("editorial") or {}
    return {
        "date": day,
        "slug": slug,
        "neighborhood": edition.get("name"),
        "lead": {"headline":_text((edition.get("lead") or {}).get("headline"),200),"dek":_text((edition.get("lead") or {}).get("dek"),420),"beat":(edition.get("lead") or {}).get("source")},
        "metrics": {key: _metric(metrics.get(key) or {}) for key in ("businesses","permits","service_requests","police")},
        "notable_records": {key: [_record(x) for x in (notable.get(key) or [])[:6]] for key in ("businesses","permits","service_requests","police")},
        "market_participants": {"owners":(participants.get("owners") or [])[:6],"general_contractors":(participants.get("general_contractors") or [])[:6],"source_note":_text(participants.get("note"),420)},
        "real_estate": _real_estate(snapshot, slug),
        "recent_reporting": _news_context(edition),
        "dining": _dining(snapshot, edition.get("name") or ""),
        "arts": _arts(snapshot, edition.get("name") or ""),
        "existing_editorial": {"analysis":_text(editorial.get("analysis"),600),"watch":_text(editorial.get("watch"),400),"signal_reason":_text(editorial.get("signal_reason"),400)},
        "previous_daily_analysis": _previous_analysis(previous_snapshot, slug),
    }

def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in payload.get("output") or []:
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                chunks.append(str(part["text"]))
    return "\n".join(chunks).strip()

def _parse_json(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(clean[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Long-read response was not a JSON object")
    return value

def _normalize(item: dict[str, Any], slug: str, day: str, model: str) -> dict[str, Any] | None:
    sections = []
    body = []
    for section in (item.get("sections") or [])[:6]:
        if not isinstance(section, dict):
            continue
        paragraphs = [_text(p, 2200) for p in (section.get("paragraphs") or []) if _text(p, 30)]
        if not paragraphs:
            continue
        heading = _text(section.get("heading"), 120)
        sections.append({"heading": heading, "paragraphs": paragraphs[:4]})
        body.extend(paragraphs[:4])
    if not body:
        body = [_text(p, 2200) for p in (item.get("body") or []) if _text(p, 30)]
        if body:
            sections = [{"heading": "", "paragraphs": body}]
    headline = _text(item.get("headline"), 210)
    dek = _text(item.get("dek"), 460)
    thesis = _text(item.get("thesis"), 460)
    outlook = _text(item.get("outlook"), 900)
    if not headline or not dek or not thesis or len(body) < 5:
        return None
    watchlist = []
    for row in (item.get("watchlist") or [])[:6]:
        if isinstance(row, dict):
            signal = _text(row.get("signal"), 220)
            meaning = _text(row.get("would_mean"), 320)
        else:
            signal, meaning = _text(row, 220), ""
        if signal:
            watchlist.append({"signal": signal, "would_mean": meaning})
    connections = []
    for row in (item.get("connections") or [])[:7]:
        if not isinstance(row, dict):
            continue
        interpretation = _text(row.get("interpretation"), 420)
        if interpretation:
            connections.append({
                "signal_a": _text(row.get("signal_a"), 120),
                "signal_b": _text(row.get("signal_b"), 120),
                "interpretation": interpretation,
                "confidence": row.get("confidence") if row.get("confidence") in {"high","medium","low"} else "medium",
            })
    word_count = len((" ".join(body) + " " + outlook).split())
    return {
        "slug": slug,
        "headline": headline,
        "dek": dek,
        "thesis": thesis,
        "thesis_status": item.get("thesis_status") if item.get("thesis_status") in {"new","strengthened","weakened","changed","mixed"} else "new",
        "body": body[:14],
        "connections": connections,
        "outlook": outlook,
        "watchlist": watchlist,
        "signals_connected": [_text(x,120) for x in (item.get("signals_connected") or [])[:10] if _text(x,5)],
        "confidence": item.get("confidence") if item.get("confidence") in {"high","medium","low"} else "medium",
        "uncertainties": [_text(x,320) for x in (item.get("uncertainties") or [])[:6] if _text(x,10)],
        "generated_for": day,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "word_count": word_count,
        "reading_minutes": max(4, math.ceil(word_count / 210)),
        "method": "gpt-5.6-neighborhood-analysis",
        "model": model,
    }

class IntelligentLongReadClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("BULLETIN_LONGREAD_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.timeout = float(os.getenv("BULLETIN_LONGREAD_TIMEOUT_SECONDS", "90"))
        self.concurrency = max(1, min(8, int(os.getenv("BULLETIN_LONGREAD_CONCURRENCY", "5"))))
        self.max_output_tokens = max(2500, min(9000, int(os.getenv("BULLETIN_LONGREAD_MAX_OUTPUT_TOKENS", "5000"))))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def generate_one(self, packet: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "instructions": EDITORIAL_INSTRUCTIONS,
            "input": "Analyze this neighborhood evidence packet and return the requested JSON object:\n\n" + json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            "max_output_tokens": self.max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.post(RESPONSES_URL, headers=headers, json=body)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 0:
                        await asyncio.sleep(1.25)
                        continue
                response.raise_for_status()
                return _parse_json(_extract_output_text(response.json()))
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.75)
        raise RuntimeError(str(last_error or "Long-read generation failed"))

    async def enrich(self, snapshot: dict[str, Any], previous_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        day = datetime.now(PACIFIC).date().isoformat()
        previous_reads = (previous_snapshot or {}).get("long_reads") or {}
        previous_meta = (previous_snapshot or {}).get("long_read_meta") or {}
        previous_intelligent = int(previous_meta.get("intelligent_count") or 0)
        previous_total = int(previous_meta.get("neighborhood_count") or len(previous_reads))
        fully_intelligent = bool(previous_reads) and previous_intelligent == previous_total and previous_total > 0
        if previous_meta.get("generated_for") == day and fully_intelligent:
            snapshot["long_reads"] = previous_reads
            snapshot["long_read_meta"] = {**previous_meta, "reused_at": datetime.now(timezone.utc).isoformat(), "reused_for_same_day": True}
            return snapshot

        editions = snapshot.get("editions") or {}
        semaphore = asyncio.Semaphore(self.concurrency)
        generated: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}

        async def run(slug: str, edition: dict[str, Any]) -> None:
            fallback = build_long_read(snapshot, slug, edition, day)
            if not self.configured:
                fallback["method"] = "deterministic-fallback"
                fallback["generation_error"] = "OPENAI_API_KEY is not configured"
                generated[slug] = fallback
                return
            packet = evidence_packet(snapshot, slug, edition, previous_snapshot, day)
            async with semaphore:
                try:
                    raw = await self.generate_one(packet)
                    normalized = _normalize(raw, slug, day, self.model)
                    if normalized is None:
                        raise ValueError("Response did not contain a complete analytical article")
                    generated[slug] = normalized
                except Exception as exc:
                    errors[slug] = f"{type(exc).__name__}: {exc}"
                    fallback["method"] = "deterministic-fallback"
                    fallback["generation_error"] = errors[slug]
                    generated[slug] = fallback

        await asyncio.gather(*(run(slug, edition) for slug, edition in editions.items()))
        intelligent_count = sum(1 for x in generated.values() if x.get("method") == "gpt-5.6-neighborhood-analysis")
        snapshot["long_reads"] = generated
        snapshot["long_read_meta"] = {
            "generated_for": day,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "neighborhood_count": len(generated),
            "intelligent_count": intelligent_count,
            "fallback_count": len(generated) - intelligent_count,
            "configured": self.configured,
            "model": self.model if self.configured else "deterministic-fallback",
            "errors": errors,
            "refresh_policy": "Generated once per America/Los_Angeles calendar day; later Bulletin refreshes reuse the day's analysis.",
            "editorial_policy": "Each article selects its own thesis and structure from the neighborhood evidence packet, compares eight-week and city context, and states observable conditions that would strengthen or weaken the outlook.",
        }
        return snapshot
