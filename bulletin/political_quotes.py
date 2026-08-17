from __future__ import annotations

from typing import Any

QUOTES: list[dict[str, Any]] = [
    {
        "person": "Daniel Lurie",
        "title": "Mayor of San Francisco",
        "date": "2025-06-04",
        "beat": "police",
        "claim": "city_crime_down",
        "quote": "We’ve been working hard—crime is down roughly 30%—but when it comes to the safety of San Franciscans, we take nothing for granted.",
        "source": "Mayor's proposed 2025–27 budget remarks",
        "source_url": "https://www.sf.gov/news-mayor-lurie-presents-balanced-responsible-budget-to-advance-san-franciscos-recovery",
    },
    {
        "person": "Daniel Lurie",
        "title": "Mayor of San Francisco",
        "date": "2025-02-13",
        "beat": "recovery",
        "claim": "business_housing_recovery",
        "quote": "San Francisco is coming back, but we need to create clearer pathways to open businesses and build housing.",
        "source": "PermitSF launch",
        "source_url": "https://www.sf.gov/mayor-lurie-launches-permit-reform-effort-with-focus-on-housing-and-small-business",
    },
    {
        "person": "Danny Sauter",
        "title": "District 3 Supervisor",
        "date": "2026-01-06",
        "beat": "police",
        "claim": "d3_crime_down",
        "quote": "Crime citywide is down nearly 30%, and nearly 40% within the Central Police District.",
        "source": "District 3 first-year newsletter",
        "source_url": "https://sfbos.org/supervisor-sauter-010106-newsletter",
    },
    {
        "person": "Shamann Walton",
        "title": "District 10 Supervisor",
        "date": "2026-03-10",
        "beat": "service_requests",
        "claim": "bayview_cleanliness",
        "quote": "Bayview deserves the same clean, healthy environment as any other neighborhood in San Francisco.",
        "source": "Bayview illegal-dumping pilot announcement",
        "source_url": "https://www.sfgate.com/news/bayarea/article/sf-community-dumpsters-to-be-placed-in-bayview-22069935.php",
    },
    {
        "person": "Connie Chan",
        "title": "District 1 Supervisor / Budget Chair",
        "date": "2026-02-01",
        "beat": "budget",
        "claim": "budget_trajectory",
        "quote": "Controller reports project that the city’s budget trajectory is finally trending in a better direction.",
        "source": "FY 2026–27 budget priorities",
        "source_url": "https://sfbos.org/supervisor-chan-budget-information",
    },
    {
        "person": "Scott Wiener",
        "title": "California State Senator",
        "date": "2025-08-05",
        "beat": "traffic",
        "claim": "speed_cameras",
        "quote": "Automated speed enforcement works to make our streets safer.",
        "source": "San Francisco speed-camera rollout",
        "source_url": "https://www.sf.gov/news-mayor-lurie-takes-major-step-to-improve-public-safety-kicks-off-new-phase-of-first-in-the-state-automated-speed-camera-program/",
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
    editions = snapshot.get("editions", {})
    selected = [e for e in editions.values() if e.get("name") in names]
    current = sum(float(e.get("metrics", {}).get(key, {}).get("current") or 0) for e in selected)
    baseline = sum(float(e.get("metrics", {}).get(key, {}).get("baseline_week") or 0) for e in selected)
    pct = ((current - baseline) / baseline * 100) if baseline >= 1 else None
    return {"current": round(current, 1), "baseline": round(baseline, 1), "pct": round(pct, 1) if pct is not None else None}


def _fmt_pct(value: float | None) -> str:
    return "not comparable" if value is None else f"{abs(value):.0f}% {'above' if value > 0 else 'below'} the recent weekly baseline"


def evaluate_quote(snapshot: dict, item: dict) -> dict:
    claim = item["claim"]
    verdict = "Not directly testable"
    tone = "neutral"
    analysis = "The current Bulletin feeds do not directly measure this claim."
    wrinkle = "This is a useful reminder that a public statement can concern an outcome our present datasets do not actually observe."
    metrics: list[dict] = []

    if claim == "city_crime_down":
        police = _metric(snapshot, "police")
        pct = police["pct"]
        metrics = [{"label": "Reported police incidents", "value": _fmt_pct(pct)}]
        if pct is not None and pct < -8:
            verdict, tone = "Directionally supported", "support"
        elif pct is not None and pct > 8:
            verdict, tone = "Current data runs the other way", "tension"
        else:
            verdict, tone = "Mixed / short-window", "mixed"
        analysis = f"The latest seven-day citywide incident count is {_fmt_pct(pct)}. That {'matches' if pct is not None and pct < 0 else 'does not match'} the direction of the Mayor’s statement, but it is not the same comparison period as the quoted 30% figure."
        wrinkle = "The exact percentage should not be treated as re-verified here: the Bulletin is comparing one week with a four-week baseline, not the Mayor’s longer reference period."

    elif claim == "business_housing_recovery":
        biz, permits = _metric(snapshot, "businesses"), _metric(snapshot, "permits")
        metrics = [
            {"label": "Business registrations", "value": _fmt_pct(biz["pct"])},
            {"label": "Building permit filings", "value": _fmt_pct(permits["pct"])},
        ]
        positive = sum(1 for x in (biz["pct"], permits["pct"]) if x is not None and x > 8)
        negative = sum(1 for x in (biz["pct"], permits["pct"]) if x is not None and x < -8)
        if positive == 2:
            verdict, tone = "Directionally supported", "support"
        elif negative == 2:
            verdict, tone = "Current data shows weaker activity", "tension"
        else:
            verdict, tone = "Mixed", "mixed"
        analysis = "The quote combines two separate recovery channels. The Bulletin can observe new business-location registrations and permit filing volume, but not whether PermitSF itself caused either movement."
        wrinkle = "A rise in registrations is not the same thing as occupied storefronts, and a permit filing is not completed housing. The direction can support the recovery story while still overstating what the records prove."

    elif claim == "d3_crime_down":
        city = _metric(snapshot, "police")
        d3 = _hood_metric(snapshot, D3_PROXY, "police")
        metrics = [
            {"label": "Citywide reported incidents", "value": _fmt_pct(city["pct"])},
            {"label": "District 3 neighborhood proxy", "value": _fmt_pct(d3["pct"])},
        ]
        if city["pct"] is not None and d3["pct"] is not None and city["pct"] < 0 and d3["pct"] < 0:
            verdict, tone = "Directionally supported", "support"
        elif city["pct"] is not None and d3["pct"] is not None and city["pct"] > 0 and d3["pct"] > 0:
            verdict, tone = "Current data runs the other way", "tension"
        else:
            verdict, tone = "Mixed", "mixed"
        analysis = "The current Bulletin window can check the direction of reported incidents, but not reproduce Sauter’s annual calculation. The District 3 figure is a proxy built from Analysis Neighborhoods, not official supervisorial boundaries."
        wrinkle = "If citywide and the District 3 proxy diverge, that is more interesting than the headline percentage: it shows why citywide crime narratives can obscure neighborhood-level movement."

    elif claim == "bayview_cleanliness":
        bay = _hood_metric(snapshot, ["Bayview Hunters Point"], "service_requests")
        metrics = [{"label": "Bayview Hunters Point 311 requests", "value": _fmt_pct(bay["pct"])}]
        verdict, tone = "Data highlights the issue; claim is normative", "mixed"
        analysis = f"Bayview Hunters Point’s latest overall 311 volume is {_fmt_pct(bay['pct'])}. That can show service pressure, but the quote is fundamentally a value statement about equal neighborhood conditions."
        wrinkle = "Illegal dumping is especially tricky: 311 counts reflect both dumping and reporting behavior, and the city has acknowledged that the category can understate the true problem."

    elif claim == "budget_trajectory":
        verdict, tone = "Not testable with current Bulletin feeds", "neutral"
        analysis = "The Bulletin currently tracks neighborhood public records, not Controller revenue forecasts, expenditure growth, reserves, or multi-year deficits."
        wrinkle = "This is a concrete data gap worth exposing rather than forcing a verdict. A future fiscal feed could compare political budget claims against Controller projections directly."

    elif claim == "speed_cameras":
        verdict, tone = "Not testable with current Bulletin feeds", "neutral"
        analysis = "Police incident and 311 data do not measure vehicle speeds, collisions, injuries, or camera-zone before/after outcomes."
        wrinkle = "The statement may be supported by transportation research, but the Bulletin should not borrow evidence from an unrelated dataset just to produce a verdict."

    return {**item, "verdict": verdict, "tone": tone, "analysis": analysis, "wrinkle": wrinkle, "metrics": metrics}


def build_quote_analysis(snapshot: dict) -> dict:
    cards = [evaluate_quote(snapshot, item) for item in QUOTES]
    counts: dict[str, int] = {}
    for card in cards:
        counts[card["tone"]] = counts.get(card["tone"], 0) + 1
    return {
        "cards": cards,
        "counts": counts,
        "methodology": "Quotes are checked only against the Bulletin datasets that actually bear on the claim. Short-window directional agreement is labeled separately from verification of a politician’s original percentage or causal explanation.",
    }
