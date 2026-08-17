from __future__ import annotations

import math, re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from .config import ANALYSIS_NEIGHBORHOODS, SOURCES, SourceConfig

FRIENDLY_311 = {
    "Graffiti Public Property": "graffiti on public property",
    "Graffiti Private Property": "graffiti on private property",
    "Street and Sidewalk Cleaning": "street and sidewalk cleaning",
    "Encampments": "encampment-related requests",
    "Abandoned Vehicle": "abandoned-vehicle reports",
    "Blocked Street or SideWalk": "blocked street or sidewalk reports",
    "Noise Report": "noise complaints",
    "General Request - PUBLIC WORKS": "Public Works requests",
    "MUNI Feedback": "Muni feedback",
    "Tree Maintenance": "tree-maintenance requests",
    "Streetlights": "streetlight requests",
}
ROUTINE_311 = {"graffiti public property", "graffiti private property", "street and sidewalk cleaning", "general request - public works"}


def slugify(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", v.lower().replace("/", "-")).strip("-")


def num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def day(v: Any) -> date:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()


def text(v: Any, n: int = 220) -> str:
    s = " ".join(str(v or "").replace("\n", " ").split()).strip()
    return s if len(s) <= n else s[: n - 1].rstrip(" ,;:-") + "…"


def label(v: Any, source: str = "") -> str:
    raw = text(v, 100) or "Other"
    return FRIENDLY_311.get(raw, raw) if source == "service_requests" else raw


def money(v: float) -> str:
    return f"${v/1_000_000:.1f}M" if v >= 1_000_000 else (f"${v/1_000:.0f}K" if v >= 1_000 else f"${v:,.0f}")


def unit_count(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def metric_stats(rows: list[dict[str, Any]], end: date) -> dict[str, Any]:
    start, base_start = end - timedelta(days=6), end - timedelta(days=34)
    current = baseline = 0
    daily: dict[date, int] = defaultdict(int)
    for r in rows:
        d, c = day(r["day"]), int(num(r.get("count")))
        daily[d] += c
        if start <= d <= end:
            current += c
        elif base_start <= d < start:
            baseline += c
    base_week = baseline / 4 if baseline else 0
    delta = current - base_week
    pct = delta / base_week * 100 if base_week >= 1 else None
    weekly = []
    for i in range(7, -1, -1):
        w_end = end - timedelta(days=7 * i)
        weekly.append(sum(v for d, v in daily.items() if w_end - timedelta(days=6) <= d <= w_end))
    mx = max(weekly) if weekly else 0
    surprise = abs(delta) / math.sqrt(base_week + 1)
    interest = min(100, surprise * 10 + math.log1p(current) * 7 + min(abs(pct or 0), 150) * .28)
    return {
        "current": current,
        "baseline_week": round(base_week, 1),
        "pct_change": round(pct, 1) if pct is not None else None,
        "interest": round(interest, 1),
        "weekly_history": weekly,
        "history_bars": [round(v / mx * 100) if mx else 0 for v in weekly],
    }


def category_stats(rows: list[dict[str, Any]], end: date, source: str) -> list[dict[str, Any]]:
    start, base_start = end - timedelta(days=6), end - timedelta(days=34)
    totals = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        d, c = day(r["day"]), num(r.get("count"))
        key = str(r.get("category") or "Uncategorized").strip()
        if start <= d <= end:
            totals[key][0] += c
        elif base_start <= d < start:
            totals[key][1] += c
    out = []
    for key, (cur, base) in totals.items():
        bw = base / 4
        pct = (cur - bw) / bw * 100 if bw >= 1 else None
        score = abs(cur - bw) / math.sqrt(bw + 1) * 8 + math.log1p(cur) * 5
        out.append({
            "category": key,
            "display_category": label(key, source),
            "current": int(cur),
            "baseline_week": round(bw, 1),
            "pct_change": round(pct, 1) if pct is not None else None,
            "interest": round(score, 1),
        })
    return sorted(out, key=lambda x: (x["interest"], x["current"]), reverse=True)


def change(s: dict[str, Any]) -> str:
    pct = s.get("pct_change")
    if pct is None:
        return "above its recent average" if s["current"] > s["baseline_week"] else "near its recent average"
    if abs(pct) < 8:
        return "roughly in line with the prior four-week average"
    return f"{abs(pct):.0f}% {'above' if pct > 0 else 'below'} the prior four-week average"


def trend(pct: float | None) -> str:
    return "held steady" if pct is None or abs(pct) < 8 else ("rose" if pct > 0 else "fell")


def top_category(items: list[dict[str, Any]], source: str) -> dict[str, Any] | None:
    items = [x for x in items if x.get("current", 0) > 0] or items
    if not items:
        return None
    if source != "service_requests":
        return items[0]
    scored = []
    for x in items:
        score = x["interest"]
        if str(x["category"]).lower() in ROUTINE_311:
            score *= .48
            if x.get("pct_change") is not None and abs(x["pct_change"]) >= 60:
                score *= 1.6
        scored.append((score, x))
    return max(scored, key=lambda p: (p[0], p[1]["current"]))[1]


def records(cfg: SourceConfig, rows: list[dict[str, Any]], hood: str) -> list[dict[str, Any]]:
    rows = [r for r in rows if str(r.get(cfg.neighborhood_field) or "").strip() == hood]
    if cfg.key == "permits":
        prepared = []
        for r in rows:
            existing_units = unit_count(r.get("existing_units"))
            proposed_units = unit_count(r.get("proposed_units"))
            unit_delta = proposed_units - existing_units if existing_units is not None and proposed_units is not None else None
            prepared.append({
                "title": text(r.get("permit_type_definition") or "Building permit", 100),
                "address": " ".join(str(r.get(k) or "").strip() for k in ("street_number", "street_name", "street_suffix")).strip(),
                "description": text(r.get("description"), 240),
                "cost": num(r.get("estimated_cost")),
                "status": text(r.get("status"), 60),
                "permit_number": text(r.get("permit_number"), 40),
                "existing_units": existing_units,
                "proposed_units": proposed_units,
                "unit_delta": unit_delta,
                "existing_use": text(r.get("existing_use"), 90),
                "proposed_use": text(r.get("proposed_use"), 90),
            })
        prepared.sort(key=lambda x: (max(x.get("unit_delta") or 0, 0), x.get("cost") or 0), reverse=True)
        return prepared[:8]
    if cfg.key == "businesses":
        out, seen = [], set()
        for r in rows:
            pair = (text(r.get("dba_name") or "New business", 100), text(r.get("full_business_address"), 120))
            if pair in seen:
                continue
            seen.add(pair)
            out.append({"title": pair[0], "address": pair[1], "owner": text(r.get("ownership_name"), 100)})
            if len(out) == 8:
                break
        return out
    if cfg.key == "service_requests":
        out, seen = [], set()
        for r in rows:
            cat = label(r.get("service_name"), cfg.key)
            sub = text(r.get("service_subtype"), 100)
            addr = text(r.get("address"), 120)
            title = sub if sub and sub.lower() != str(r.get("service_name") or "").lower() else cat
            if (title, addr) in seen:
                continue
            seen.add((title, addr))
            detail = text(r.get("service_details"), 150)
            out.append({
                "title": title,
                "category": cat,
                "address": addr,
                "description": detail if detail.lower() not in {title.lower(), cat.lower()} else "",
                "status": text(r.get("status_description"), 40),
            })
            if len(out) == 8:
                break
        return out
    if cfg.key == "police":
        c = Counter((text(r.get("incident_category"), 100), text(r.get("incident_subcategory") or r.get("incident_description"), 120)) for r in rows)
        return [{"title": sub or cat, "category": cat, "count": count} for (cat, sub), count in c.most_common(8) if cat or sub]
    return []


def story(cfg: SourceConfig, hood: str, s: dict[str, Any], cats: list[dict[str, Any]], recs: list[dict[str, Any]]) -> dict[str, Any]:
    n, pct, top = s["current"], s.get("pct_change"), top_category(cats, cfg.key)
    score, facts, topic = s["interest"] * cfg.editorial_weight, [], cfg.key
    if cfg.key == "businesses":
        first = recs[0] if recs else None
        title = (f"{first['title']} registers a new {hood} location" if n == 1 else f"{first['title']} is among {n} new business locations registered") if first else f"{n} new business locations registered in {hood}"
        detail = f"The filing lists {first['address']}." if first and first.get("address") else "The latest business-location records show new registrations across the neighborhood."
        dek = f"Registrations are {change(s)}. {detail}"
        facts = [f"{n} new location registration{'s' if n != 1 else ''} in the latest source window."]
        if len(recs) > 1:
            facts.append("Also newly registered: " + "; ".join(x["title"] for x in recs[1:3]) + ".")
        topic = "business-registrations"
        score += min(14, n * 1.8)
    elif cfg.key == "permits":
        first = recs[0] if recs else None
        housing = next((x for x in recs if (x.get("unit_delta") or 0) > 0 and x.get("address")), None)
        if housing:
            delta = housing["unit_delta"]
            title = f"Permit filing proposes {delta} net new housing unit{'s' if delta != 1 else ''} at {housing['address']}"
            if housing.get("existing_units") is not None and housing.get("proposed_units") is not None:
                detail = f"The filing would change the listed unit count from {housing['existing_units']} to {housing['proposed_units']}."
            else:
                detail = "The filing lists an increase in residential units."
            if housing.get("proposed_use") and housing.get("proposed_use") != housing.get("existing_use"):
                detail += f" Proposed use: {housing['proposed_use']}."
            topic = "housing-development"
            score += min(44, 14 + delta * 4)
            if housing.get("cost"):
                score += min(10, math.log10(max(housing["cost"], 1)) * 1.5)
        elif first and first.get("cost", 0) >= 250_000 and first.get("address"):
            title = f"{money(first['cost'])} permit filing stands out at {first['address']}"
            detail = first.get("description") or "The filing is one of the week's larger development records."
            topic = "development"
        elif first and first.get("address"):
            title = f"{first['title']} filed at {first['address']}"
            detail = first.get("description") or f"It is one of {n} permit filings in the latest window."
            topic = "development"
        elif top:
            title = f"{top['display_category']} leads {hood}'s latest permit filings"
            detail = f"The category accounts for {top['current']} of {n} filings."
            topic = "development"
        else:
            title, detail, topic = f"{n} building permits filed across {hood}", "The filings span the latest seven-day permit window.", "development"
        dek = f"Permit activity is {change(s)}. {text(detail, 250)}"
        facts = [f"{n} permit filing{'s' if n != 1 else ''} in the latest window."]
        if housing:
            facts.append(f"Proposed unit count: {housing.get('existing_units', '—')} → {housing.get('proposed_units', '—')}.")
            if housing.get("cost"):
                facts.append(f"Listed estimated cost: {money(housing['cost'])}.")
        else:
            if first and first.get("cost"):
                facts.append(f"Largest listed estimated cost: {money(first['cost'])}.")
            if top:
                facts.append(f"Most active permit type: {top['display_category']} ({top['current']}).")
        if first and first.get("cost", 0) >= 1_000_000:
            score += min(32, math.log10(first["cost"]) * 4.5)
    elif cfg.key == "service_requests":
        if top:
            name, tpct = top["display_category"], top.get("pct_change")
            topic = "311-" + slugify(name)
            title = f"{name.capitalize()} {trend(tpct)} in {hood}'s latest 311 data" if tpct is not None and abs(tpct) >= 20 and top["current"] >= 3 else f"311 volume {trend(pct)} as {name} led service requests"
            detail = f"{name.capitalize()} accounted for {top['current']} of {n} requests, versus a prior four-week weekly average of {top['baseline_week']:.1f}."
        else:
            title, detail = f"{n} 311 requests logged across {hood}", "The public service-request feed was broadly distributed across categories."
        dek = f"Overall 311 activity is {change(s)}. {detail}"
        facts = [f"{x['display_category'].capitalize()}: {x['current']} requests." for x in cats[:3]]
        if top and str(top["category"]).lower() in ROUTINE_311:
            score *= .62
        if pct is None or abs(pct) < 15:
            score *= .82
    else:
        if top and top["current"] >= 2:
            name, tpct = top["display_category"], top.get("pct_change")
            topic = "police-" + slugify(name)
            title = f"{name} reports {trend(tpct)} in the latest police data" if tpct is not None and abs(tpct) >= 18 else f"{name} is the largest category in the latest police report data"
            detail = f"The category accounts for {top['current']} of {n} reported incidents in the seven-day source window."
        else:
            title, detail = f"Reported police incidents {trend(pct)} from the recent average", f"The dataset contains {n} reports in the latest seven-day period."
        dek = f"Overall incident-report volume is {change(s)}. {detail}"
        facts = [f"{x['display_category']}: {x['current']} reports." for x in cats[:3]]
        score *= .92
    if n == 0:
        score = -20
    return {
        "source": cfg.key,
        "current": n,
        "section": cfg.section,
        "headline": text(title, 150),
        "dek": text(dek, 380),
        "facts": facts[:3],
        "interest": round(score, 1),
        "source_url": cfg.source_url,
        "topic_key": topic,
    }


def quick_read(e: dict[str, Any]) -> list[dict[str, str]]:
    out, note, m = [], e.get("notable", {}), e.get("metrics", {})
    if note.get("businesses"):
        x = note["businesses"][0]
        out.append({"label": "Business", "text": x["title"] + (f" — {x['address']}" if x.get("address") else "")})
    if note.get("permits"):
        housing = next((x for x in note["permits"] if (x.get("unit_delta") or 0) > 0), None)
        x = housing or note["permits"][0]
        t = x.get("address") or x.get("title") or "Permit filing"
        if housing:
            out.append({"label": "Housing", "text": f"+{housing['unit_delta']} proposed units — {t}"})
        else:
            out.append({"label": "Development", "text": f"{money(x['cost'])} filing at {t}" if x.get("cost") else t})
    x = top_category(m.get("service_requests", {}).get("categories") or [], "service_requests")
    if x:
        out.append({"label": "City services", "text": f"{x['display_category'].capitalize()}: {x['current']} requests"})
    cats = m.get("police", {}).get("categories") or []
    if cats and cats[0].get("current", 0) > 0:
        out.append({"label": "Public safety", "text": f"{cats[0]['display_category']}: {cats[0]['current']} reports"})
    return out[:4]


def front_page(editions: dict[str, dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    candidates = sorted(
        ({"name": e["name"], "slug": e["slug"], **s} for e in editions.values() for s in e.get("stories", [])),
        key=lambda x: x["interest"],
        reverse=True,
    )
    chosen, hoods, sources, topics = [], set(), Counter(), Counter()
    caps = {"permits": 4, "businesses": 4, "service_requests": 2, "police": 2}
    for x in candidates:
        if x["current"] <= 0 or x["slug"] in hoods or sources[x["source"]] >= caps.get(x["source"], 3) or topics[x["topic_key"]] >= 2:
            continue
        chosen.append(x)
        hoods.add(x["slug"])
        sources[x["source"]] += 1
        topics[x["topic_key"]] += 1
        if len(chosen) == limit:
            return chosen
    for x in candidates:
        if len(chosen) == limit:
            break
        if x["current"] > 0 and x["slug"] not in hoods:
            chosen.append(x)
            hoods.add(x["slug"])
    return chosen


def build_snapshot(raw_sources: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]:
    raw = {r["key"]: r for r in raw_sources}
    observed = {str(x.get("neighborhood") or "").strip() for r in raw_sources for x in r.get("daily", []) if x.get("neighborhood")}
    hoods = list(ANALYSIS_NEIGHBORHOODS) + sorted(observed - set(ANALYSIS_NEIGHBORHOODS))
    editions, recency, city = {}, {}, defaultdict(list)
    for hood in hoods:
        metrics, notes, stories = {}, {}, []
        for cfg in SOURCES:
            r = raw.get(cfg.key)
            if not r:
                continue
            end = date.fromisoformat(r["latest"])
            recency[cfg.key] = r["latest"]
            daily = [x for x in r.get("daily", []) if str(x.get("neighborhood") or "").strip() == hood]
            catrows = [x for x in r.get("categories", []) if str(x.get("neighborhood") or "").strip() == hood]
            stats = metric_stats(daily, end)
            cats = category_stats(catrows, end, cfg.key)
            recs = records(cfg, r.get("recent", []), hood)
            notes[cfg.key] = recs
            metrics[cfg.key] = {
                **stats,
                "short_label": cfg.short_label,
                "section": cfg.section,
                "categories": cats[:10],
                "source_url": cfg.source_url,
                "latest": r["latest"],
            }
            city[cfg.key].append(stats["current"])
            stories.append(story(cfg, hood, stats, cats, recs))
        stories.sort(key=lambda x: x["interest"], reverse=True)
        key = slugify(hood)
        editions[key] = {"name": hood, "slug": key, "metrics": metrics, "lead": stories[0] if stories else None, "stories": stories, "notable": notes}
    for e in editions.values():
        for key, m in e["metrics"].items():
            vals = sorted(city[key], reverse=True)
            m["city_median"] = median(vals) if vals else 0
            m["city_rank"] = vals.index(m["current"]) + 1 if m["current"] in vals else None
            m["city_total_neighborhoods"] = len(vals)
        e["quick_read"] = quick_read(e)
    return {
        "generated_at": generated_at.isoformat(),
        "source_recency": recency,
        "front_page": front_page(editions),
        "editions": editions,
        "neighborhoods": [{"name": e["name"], "slug": e["slug"]} for e in editions.values()],
        "methodology": {
            "current_window": "Trailing 7 days",
            "baseline": "Average weekly count during the preceding 28 days",
            "editorial": "Routine high-volume categories are downweighted so the front page surfaces a broader mix of neighborhood developments.",
        },
    }
