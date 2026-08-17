from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from .config import ANALYSIS_NEIGHBORHOODS, SOURCES, SourceConfig


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower().replace("/", "-")).strip("-")


def parse_day(value: str) -> date:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def metric_stats(rows: list[dict[str, Any]], end_day: date) -> dict[str, Any]:
    current_start = end_day - timedelta(days=6)
    baseline_start = current_start - timedelta(days=28)
    current = baseline = 0
    by_day: dict[date, int] = defaultdict(int)
    for row in rows:
        day = parse_day(row["day"])
        count = int(num(row.get("count")))
        by_day[day] += count
        if current_start <= day <= end_day:
            current += count
        elif baseline_start <= day < current_start:
            baseline += count
    baseline_week = baseline / 4 if baseline else 0
    delta = current - baseline_week
    pct = delta / baseline_week * 100 if baseline_week >= 1 else None
    weekly = []
    for i in range(8):
        w_end = end_day - timedelta(days=7 * i)
        w_start = w_end - timedelta(days=6)
        weekly.append(sum(v for d, v in by_day.items() if w_start <= d <= w_end))
    weekly.reverse()
    surprise = abs(delta) / math.sqrt(baseline_week + 1)
    interest = min(100, surprise * 10 + math.log1p(current) * 7 + min(abs(pct or 0), 150) * .28)
    return {
        "current": current,
        "baseline_week": round(baseline_week, 1),
        "pct_change": round(pct, 1) if pct is not None else None,
        "interest": round(interest, 1),
        "weekly_history": weekly,
    }


def category_stats(rows: list[dict[str, Any]], end_day: date) -> list[dict[str, Any]]:
    current_start = end_day - timedelta(days=6)
    baseline_start = current_start - timedelta(days=28)
    totals = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        category = str(row.get("category") or "Uncategorized").strip()
        day = parse_day(row["day"])
        count = num(row.get("count"))
        if current_start <= day <= end_day:
            totals[category][0] += count
        elif baseline_start <= day < current_start:
            totals[category][1] += count
    output = []
    for category, (current, baseline) in totals.items():
        baseline_week = baseline / 4
        pct = (current - baseline_week) / baseline_week * 100 if baseline_week >= 1 else None
        score = abs(current - baseline_week) / math.sqrt(baseline_week + 1) * 8 + math.log1p(current) * 5
        output.append({"category": category, "current": int(current), "pct_change": round(pct, 1) if pct is not None else None, "interest": round(score, 1)})
    return sorted(output, key=lambda x: (x["interest"], x["current"]), reverse=True)


def change_phrase(stats: dict[str, Any]) -> str:
    pct = stats.get("pct_change")
    if pct is None:
        return "above its recent average" if stats["current"] > stats["baseline_week"] else "near its recent average"
    if abs(pct) < 8:
        return "roughly in line with the prior four-week average"
    return f"{abs(pct):.0f}% {'above' if pct > 0 else 'below'} the prior four-week average"


def headline(config: SourceConfig, neighborhood: str, stats: dict[str, Any], categories: list[dict[str, Any]]) -> tuple[str, str]:
    count = stats["current"]
    pct = stats.get("pct_change") or 0
    top = categories[0] if categories else None
    if config.key == "businesses":
        title = f"New business registrations pick up in {neighborhood}" if pct >= 25 else f"{count} new business locations registered this week"
        dek = f"New location registrations are {change_phrase(stats)}."
    elif config.key == "permits":
        title = f"{top['category']} filings lead this week's permit activity" if top and top["current"] >= 2 else f"{count} building permits filed across {neighborhood}"
        dek = f"Permit filings are {change_phrase(stats)}."
    elif config.key == "service_requests":
        title = f"{top['category']} leads this week's 311 activity" if top and top["current"] >= 4 else "311 activity shapes this week's civic-service picture"
        dek = f"Residents logged {count} service requests, {change_phrase(stats)}."
    else:
        title = "Reported police incidents ease from recent levels" if pct <= -15 else ("Reported police incidents run above the recent average" if pct >= 15 else "Reported police incidents remain near recent levels")
        dek = f"The public incident dataset shows {count} reports in the latest seven-day period, {change_phrase(stats)}."
    return title, dek


def notable_records(config: SourceConfig, rows: list[dict[str, Any]], neighborhood: str) -> list[dict[str, Any]]:
    matching = [r.copy() for r in rows if str(r.get(config.neighborhood_field) or "").strip() == neighborhood]
    if config.key == "permits":
        matching.sort(key=lambda r: num(r.get("estimated_cost")), reverse=True)
        return [{
            "title": r.get("permit_type_definition") or "Building permit",
            "address": " ".join(str(r.get(k) or "").strip() for k in ("street_number", "street_name", "street_suffix")).strip(),
            "description": str(r.get("description") or "").strip(),
            "cost": num(r.get("estimated_cost")),
        } for r in matching[:5]]
    if config.key == "businesses":
        seen, out = set(), []
        for r in matching:
            item = (str(r.get("dba_name") or "New business").strip(), str(r.get("full_business_address") or "").strip())
            if item in seen:
                continue
            seen.add(item)
            out.append({"title": item[0], "address": item[1]})
            if len(out) == 6:
                break
        return out
    return []


def build_snapshot(raw_sources: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]:
    raw_by_key = {r["key"]: r for r in raw_sources}
    observed = {str(row.get("neighborhood") or "").strip() for src in raw_sources for row in src.get("daily", []) if row.get("neighborhood")}
    neighborhoods = list(ANALYSIS_NEIGHBORHOODS) + sorted(observed - set(ANALYSIS_NEIGHBORHOODS))
    editions, source_recency, city_values = {}, {}, defaultdict(list)

    for neighborhood in neighborhoods:
        metrics, stories, notable = {}, [], {}
        for config in SOURCES:
            raw = raw_by_key.get(config.key)
            if not raw:
                continue
            end_day = date.fromisoformat(raw["latest"])
            source_recency[config.key] = raw["latest"]
            daily = [r for r in raw.get("daily", []) if str(r.get("neighborhood") or "").strip() == neighborhood]
            cats = [r for r in raw.get("categories", []) if str(r.get("neighborhood") or "").strip() == neighborhood]
            stats = metric_stats(daily, end_day)
            categories = category_stats(cats, end_day)
            metrics[config.key] = {**stats, "short_label": config.short_label, "section": config.section, "categories": categories[:8], "source_url": config.source_url}
            city_values[config.key].append(stats["current"])
            title, dek = headline(config, neighborhood, stats, categories)
            stories.append({"source": config.key, "section": config.section, "headline": title, "dek": dek, "interest": stats["interest"], "source_url": config.source_url})
            notable[config.key] = notable_records(config, raw.get("recent", []), neighborhood)
        top_permit = (notable.get("permits") or [None])[0]
        if top_permit and top_permit.get("cost", 0) >= 1_000_000:
            for story in stories:
                if story["source"] == "permits":
                    cost = top_permit["cost"]
                    story["interest"] += min(30, math.log10(cost) * 4)
                    story["headline"] = f"${cost / 1_000_000:.1f}M permit filing leads this week's development activity"
        stories.sort(key=lambda x: x["interest"], reverse=True)
        editions[slugify(neighborhood)] = {"name": neighborhood, "slug": slugify(neighborhood), "metrics": metrics, "lead": stories[0] if stories else None, "stories": stories, "notable": notable}

    for edition in editions.values():
        for key, metric in edition["metrics"].items():
            values = sorted(city_values[key], reverse=True)
            metric["city_median"] = median(values) if values else 0
            metric["city_rank"] = values.index(metric["current"]) + 1 if metric["current"] in values else None
            metric["city_total_neighborhoods"] = len(values)

    front_page = [{"name": e["name"], "slug": e["slug"], **e["lead"]} for e in editions.values() if e["lead"]]
    front_page.sort(key=lambda x: x["interest"], reverse=True)
    return {
        "generated_at": generated_at.isoformat(),
        "source_recency": source_recency,
        "front_page": front_page[:12],
        "editions": editions,
        "neighborhoods": [{"name": e["name"], "slug": e["slug"]} for e in editions.values()],
        "methodology": {"current_window": "Trailing 7 days", "baseline": "Average weekly count during the preceding 28 days"},
    }
