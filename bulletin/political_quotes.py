from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

QUOTES: list[dict[str, Any]] = [
    {
        "person": "Daniel Lurie",
        "title": "Mayor of San Francisco",
        "quote_date": "2026-01-21",
        "date": "January 21, 2026",
        "beat": "recovery",
        "claim": "city_investment",
        "quote": "People are hearing the news about San Francisco. They are investing in our city.",
        "source": "KQED Political Breakdown",
        "source_url": "https://www.kqed.org/news/12070484/tune-in-tonight-san-francisco-mayor-daniel-lurie-live-on-kqed",
    },
    {
        "person": "Danny Sauter",
        "title": "District 3 Supervisor",
        "quote_date": "2026-01-06",
        "date": "January 2026",
        "beat": "police",
        "claim": "d3_crime_down",
        "quote": "Crime citywide is down nearly 30%, and nearly 40% within the Central Police District.",
        "source": "District 3 first-year newsletter",
        "source_url": "https://sfbos.org/supervisor-sauter-010106-newsletter",
    },
    {
        "person": "Danny Sauter",
        "title": "District 3 Supervisor",
        "quote_date": "2026-01-06",
        "date": "January 2026",
        "beat": "businesses",
        "claim": "d3_business_growth",
        "quote": "This package of common-sense reforms will make it easier for small businesses to open and grow in District 3.",
        "source": "District 3 first-year newsletter",
        "source_url": "https://sfbos.org/supervisor-sauter-010106-newsletter",
    },
    {
        "person": "Shamann Walton",
        "title": "District 10 Supervisor",
        "quote_date": "2026-03-10",
        "date": "March 10, 2026",
        "beat": "service_requests",
        "claim": "bayview_cleanliness",
        "quote": "Bayview deserves the same clean, healthy environment as any other neighborhood in San Francisco.",
        "source": "Bayview illegal-dumping pilot announcement",
        "source_url": "https://www.sfgate.com/news/bayarea/article/sf-community-dumpsters-to-be-placed-in-bayview-22069935.php",
    },
]

D3_PROXY = ["Chinatown", "Financial District/South Beach", "Nob Hill", "North Beach", "Russian Hill"]


def _metric(snapshot: dict, key: str) -> dict[str, float | None]:
    rows = [e.get("metrics", {}).get(key) for e in snapshot.get("editions", {}).values()]
    rows = [m for m in rows if m]
    current = sum(float(m.get("current") or 0) for m in rows)
    baseline = sum(float(m.get("baseline_week") or 0) for m in rows)
    pct = ((current - baseline) / baseline * 100) if baseline >= 1 else None
    return {"current": round(current, 1), "baseline": round(baseline, 1), "pct": round(pct, 1) if pct is not None else None}


def _hood_metric(snapshot: dict, names: list[str], key: str) -> dict[str, float | None]:
    selected = [e for e in snapshot.get("editions", {}).values() if e.get("name") in names]
    current = sum(float(e.get("metrics", {}).get(key, {}).get("current") or 0) for e in selected)
    baseline = sum(float(e.get("metrics", {}).get(key, {}).get("baseline_week") or 0) for e in selected)
    pct = ((current - baseline) / baseline * 100) if baseline >= 1 else None
    return {"current": round(current, 1), "baseline": round(baseline, 1), "pct": round(pct, 1) if pct is not None else None}


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "without a comparable recent baseline"
    if abs(value) < 8:
        return "roughly in line with the recent weekly baseline"
    return f"{abs(value):.0f}% {'above' if value > 0 else 'below'} the recent weekly baseline"


def _direction(value: float | None) -> int:
    if value is None or abs(value) < 8:
        return 0
    return 1 if value > 0 else -1


def evaluate_quote(snapshot: dict, item: dict) -> dict:
    claim = item["claim"]
    verdict = "Mixed"
    tone = "mixed"
    analysis = "The current Bulletin data provides partial context for this statement."
    wrinkle = "The weekly public-record window is useful for direction, but it should not be treated as a full evaluation of policy effectiveness."
    metrics: list[dict] = []

    if claim == "city_investment":
        biz = _metric(snapshot, "businesses")
        permits = _metric(snapshot, "permits")
        metrics = [
            {"label": "Business registrations", "value": _fmt_pct(biz["pct"])},
            {"label": "Building permit filings", "value": _fmt_pct(permits["pct"])},
        ]
        directions = [_direction(biz["pct"]), _direction(permits["pct"])]
        if all(d >= 0 for d in directions) and any(d > 0 for d in directions):
            verdict, tone = "Directionally supported", "support"
        elif all(d <= 0 for d in directions) and any(d < 0 for d in directions):
            verdict, tone = "Current data shows softer activity", "tension"
        analysis = "Business-location registrations and permit filings are two public-record proxies for people putting money and plans into San Francisco. The latest snapshot shows whether those channels are strengthening or softening relative to their recent weekly pace."
        wrinkle = "Neither metric measures investment dollars directly. A registration may be administrative, and a permit filing may never become construction, so the strongest signal is when both move together."

    elif claim == "d3_crime_down":
        city = _metric(snapshot, "police")
        d3 = _hood_metric(snapshot, D3_PROXY, "police")
        metrics = [
            {"label": "Citywide reported incidents", "value": _fmt_pct(city["pct"])},
            {"label": "District 3 neighborhood proxy", "value": _fmt_pct(d3["pct"])},
        ]
        city_dir, d3_dir = _direction(city["pct"]), _direction(d3["pct"])
        if city_dir <= 0 and d3_dir <= 0 and (city_dir < 0 or d3_dir < 0):
            verdict, tone = "Directionally supported", "support"
        elif city_dir > 0 and d3_dir > 0:
            verdict, tone = "Current data runs the other way", "tension"
        analysis = "The current Bulletin window can test whether reported incidents are still moving downward citywide and across a District 3 neighborhood proxy, but it does not reproduce Sauter’s annual 30% and 40% calculations."
        wrinkle = "The most useful signal is divergence: if the citywide count and the District 3 proxy move differently, a single citywide crime narrative can hide important neighborhood variation."

    elif claim == "d3_business_growth":
        d3 = _hood_metric(snapshot, D3_PROXY, "businesses")
        metrics = [{"label": "District 3 business-registration proxy", "value": _fmt_pct(d3["pct"])}]
        direction = _direction(d3["pct"])
        if direction > 0:
            verdict, tone = "Directionally supported", "support"
        elif direction < 0:
            verdict, tone = "Current data runs the other way", "tension"
        analysis = "New business-location registrations across the District 3 neighborhood proxy show whether openings and location activity are running above or below their recent pace. That bears on the outcome Sauter wants, though it cannot isolate the effect of his legislation."
        wrinkle = "The distinction between outcome and cause matters: stronger registrations can support the claim that the district is becoming more active without proving that a particular reform produced the increase."

    elif claim == "bayview_cleanliness":
        bay = _hood_metric(snapshot, ["Bayview Hunters Point"], "service_requests")
        metrics = [{"label": "Bayview Hunters Point 311 requests", "value": _fmt_pct(bay["pct"])}]
        direction = _direction(bay["pct"])
        if direction > 0:
            verdict, tone = "Service pressure is elevated", "tension"
        elif direction < 0:
            verdict, tone = "Directionally improving", "support"
        analysis = "Overall 311 activity in Bayview Hunters Point is a rough measure of service pressure and reported street conditions. The latest change helps show whether residents are reporting more or fewer issues than in the preceding weeks."
        wrinkle = "311 is partly a measure of reporting behavior, not just conditions. Illegal dumping and cleanliness problems can be underreported, so a lower request count should not automatically be read as a cleaner neighborhood."

    return {**item, "verdict": verdict, "tone": tone, "analysis": analysis, "wrinkle": wrinkle, "metrics": metrics}


def build_quote_analysis(snapshot: dict) -> dict:
    generated = snapshot.get("generated_at")
    try:
        current_year = datetime.fromisoformat(str(generated).replace("Z", "+00:00")).year
    except Exception:
        current_year = datetime.now(timezone.utc).year

    current_quotes = [item for item in QUOTES if int(item["quote_date"][:4]) == current_year]
    cards = [evaluate_quote(snapshot, item) for item in current_quotes]
    cards = [card for card in cards if card["tone"] in {"support", "mixed", "tension"}]

    counts: dict[str, int] = {}
    for card in cards:
        counts[card["tone"]] = counts.get(card["tone"], 0) + 1

    return {
        "year": current_year,
        "cards": cards,
        "counts": counts,
        "methodology": "The page includes only statements from the current calendar year that the Bulletin’s existing feeds can meaningfully illuminate. Verdicts compare the latest seven-day public-record window with the preceding four-week weekly baseline; they test current direction, not a politician’s original long-run percentage or causal explanation.",
    }
