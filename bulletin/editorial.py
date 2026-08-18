from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

BEATS = {
    "businesses": "Business & storefronts",
    "permits": "Development & housing",
    "service_requests": "Streets & city services",
    "police": "Public safety",
}
ALIASES = {
    "Bayview Hunters Point": ["bayview", "hunters point", "shipyard"],
    "Financial District/South Beach": ["financial district", "fidi", "south beach", "downtown san francisco"],
    "Castro/Upper Market": ["castro", "upper market"],
    "Oceanview/Merced/Ingleside": ["oceanview", "merced", "ingleside"],
    "South of Market": ["south of market", "soma"],
    "Sunset/Parkside": ["sunset", "parkside"],
    "Potrero Hill": ["potrero hill", "dogpatch", "power station"],
    "Mission": ["mission district", "the mission", "mission street"],
    "Chinatown": ["chinatown", "portsmouth square"],
    "Western Addition": ["western addition", "fillmore"],
}
ROUTINE_311 = ("graffiti", "street and sidewalk cleaning", "public works requests")


def norm(v):
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


def published(item):
    try:
        d = datetime.fromisoformat(str(item.get("published") or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def recent(item, now, days=50):
    return published(item) >= now - timedelta(days=days)


def aliases(name):
    vals = [name.lower(), *ALIASES.get(name, [])]
    if "/" in name:
        vals += [x.strip().lower() for x in name.split("/") if len(x.strip()) > 3]
    return list(dict.fromkeys(vals))


def article_key(item):
    title = str(item.get("title") or "")
    publisher = str(item.get("publisher") or "")
    if publisher and title.lower().endswith(" - " + publisher.lower()):
        title = title[: -(len(publisher) + 3)]
    return norm(title)


def record_terms(e):
    n = e.get("notable", {})
    out = []
    out += [norm(x.get("title")) for x in n.get("businesses", [])[:4] if len(norm(x.get("title"))) > 4]
    out += [norm(x.get("address")) for x in n.get("businesses", [])[:3] if len(norm(x.get("address"))) > 4]
    out += [norm(x.get("address")) for x in n.get("permits", [])[:4] if len(norm(x.get("address"))) > 4]
    out += [norm(x.get("description")) for x in n.get("permits", [])[:2] if len(norm(x.get("description"))) > 12]
    return [x for x in dict.fromkeys(out) if x]


def story_for(e, key):
    return next((story for story in e.get("stories", []) if story.get("source") == key), {})


def signal_score(e, key=None):
    story = story_for(e, key) if key else (e.get("lead") or {})
    key = key or story.get("source")
    if not key:
        return 0.0
    m = e.get("metrics", {}).get(key, {})
    current = float(m.get("current") or 0)
    baseline = float(m.get("baseline_week") or 0)
    pct = abs(float(m.get("pct_change") or 0))
    score = float(story.get("interest") or 0) + min(abs(current - baseline) * 2.2, 24) + min(pct / 6, 16)
    notable = e.get("notable", {}).get(key, [])

    if key == "permits":
        housing = next((x for x in notable if (x.get("unit_delta") or 0) > 0), None)
        biggest_cost = max((float(x.get("cost") or 0) for x in notable), default=0)
        use_change = next((x for x in notable if x.get("proposed_use") and x.get("proposed_use") != x.get("existing_use")), None)
        if housing:
            score += min(36, 14 + float(housing.get("unit_delta") or 0) * 3.2)
        if biggest_cost >= 1_000_000:
            score += min(22, 7 + math.log10(biggest_cost) * 2)
        if use_change:
            score += 8
        if notable and all("minor alterations" in norm(x.get("title")) for x in notable[:3]):
            score -= 20
    elif key == "businesses":
        if notable:
            score += 7
        if current < 2 and pct < 35:
            score -= 12
    elif key == "service_requests":
        categories = m.get("categories") or []
        top = norm(categories[0].get("display_category")) if categories else ""
        if any(term in top for term in ROUTINE_311) and pct < 60:
            score -= 24
        if current < 5:
            score -= 12
        if pct >= 50 and current >= 8:
            score += 8
    elif key == "police":
        if current < 3:
            score -= 18
        if pct >= 40 and current >= 4:
            score += 10
    return round(score, 1)


def significance_reason(e, key=None):
    story = story_for(e, key) if key else (e.get("lead") or {})
    key = key or story.get("source")
    m = e.get("metrics", {}).get(key, {})
    notable = e.get("notable", {}).get(key, [])
    pct = m.get("pct_change")

    if key == "permits":
        housing = next((x for x in notable if (x.get("unit_delta") or 0) > 0), None)
        if housing:
            return f"The filing proposes {housing['unit_delta']} net new housing unit{'s' if housing['unit_delta'] != 1 else ''}."
        biggest = max(notable, key=lambda x: float(x.get("cost") or 0), default=None)
        if biggest and float(biggest.get("cost") or 0) >= 1_000_000:
            return f"The largest visible filing lists about ${float(biggest['cost'])/1_000_000:.1f} million in estimated work."
        changed = next((x for x in notable if x.get("proposed_use") and x.get("proposed_use") != x.get("existing_use")), None)
        if changed:
            return f"The filing changes the listed use from {changed.get('existing_use') or 'not listed'} to {changed.get('proposed_use')}."
    if key == "businesses" and notable:
        return f"The signal includes a named registration for {notable[0].get('title')}."
    if pct is not None and abs(pct) >= 35:
        return f"The latest seven-day count is {abs(pct):.0f}% {'above' if pct > 0 else 'below'} its prior four-week weekly average."
    return "The signal ranks among the strongest current departures from the neighborhood's recent baseline."


def coverage_candidates(e, items, now):
    out = []
    hood = e["name"]
    lead = (e.get("lead") or {}).get("source")
    terms = record_terms(e)
    for item in items:
        if not recent(item, now):
            continue
        body = norm((item.get("title") or "") + " " + (item.get("summary") or ""))
        explicit = hood in (item.get("neighborhoods") or [])
        targeted = hood in (item.get("target_neighborhoods") or [])
        hood_hit = explicit or any(norm(a) and norm(a) in body for a in aliases(hood))
        rec_hits = [t for t in terms if len(t) > 5 and t in body]
        beat_match = item.get("beat") == lead
        targeted_beat = targeted and item.get("target_signal") == lead

        if not targeted and not hood_hit and not rec_hits:
            continue

        score = 0
        if targeted_beat:
            score += 22
        elif targeted:
            score += 14
        if rec_hits:
            score += 18 + min(len(rec_hits) * 3, 9)
        if explicit:
            score += 12
        elif hood_hit:
            score += 8
        if beat_match:
            score += 6
        if item.get("live") is False:
            score += 2
        age_days = max(0, (now - published(item)).days)
        score += max(0, 5 - age_days / 5)

        if score < 12:
            continue
        reason_parts = []
        if rec_hits:
            reason_parts.append("matches a named filing, business or address")
        elif targeted:
            reason_parts.append("surfaced by a targeted search for this data signal")
        elif hood_hit:
            reason_parts.append("names the neighborhood")
        if beat_match:
            reason_parts.append(f"covers {BEATS.get(lead, 'the same beat').lower()}")
        reason = " and ".join(reason_parts)
        out.append((score, published(item), {**item, "match_reason": reason[:180], "match_score": round(score, 1)}))
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in out]


def assign_coverage(snapshot, items, now):
    ranked = sorted(snapshot.get("editions", {}).values(), key=lambda e: signal_score(e), reverse=True)
    article_usage = Counter()
    publisher_usage = Counter()
    assignments = {}

    for e in ranked:
        score = signal_score(e)
        if score < 45:
            assignments[e["slug"]] = []
            continue
        chosen = []
        used_publishers = set()
        for item in coverage_candidates(e, items, now):
            key = article_key(item)
            publisher = norm(item.get("publisher"))
            if not key:
                continue
            # Primary crossover articles are globally unique. Secondary neighborhood context
            # may be reused once, but not repeatedly across the paper.
            allowed = 0 if not chosen else 1
            if article_usage[key] > allowed:
                continue
            if publisher and publisher in used_publishers:
                continue
            if publisher_usage[publisher] >= 7 and len(chosen) == 0:
                continue
            chosen.append(item)
            article_usage[key] += 1
            if publisher:
                publisher_usage[publisher] += 1
                used_publishers.add(publisher)
            if len(chosen) >= 2:
                break
        assignments[e["slug"]] = chosen
    return assignments


def why_for(e, cov):
    lead = e.get("lead") or {}
    key = lead.get("source")
    m = e.get("metrics", {}).get(key, {})
    pct = m.get("pct_change")
    direction = "above" if pct is not None and pct > 8 else ("below" if pct is not None and pct < -8 else "near")
    mag = f"{abs(pct):.0f}% " if pct is not None else ""
    if key == "businesses":
        h = "Why the storefront numbers may be moving"
        a = f"New business-location registrations are {mag}{direction} the neighborhood's recent weekly average. Registrations can reflect real openings, relocations, ownership changes or administrative filings, so the named storefronts matter more than the count alone."
        w = "Watch whether registrations keep appearing on the same commercial corridors; persistence is a stronger signal than a one-week burst."
    elif key == "permits":
        housing = next((x for x in e.get("notable", {}).get("permits", []) if (x.get("unit_delta") or 0) > 0), None)
        h = "Why development activity may be shifting"
        a = f"Permit activity is {mag}{direction} its recent average. " + (f"The mix includes a filing proposing {housing['unit_delta']} net new housing units, making the signal more meaningful than routine alterations." if housing else "Weekly permit counts are lumpy, so project scale, use changes and housing-unit changes are better clues to the development cycle than volume alone.")
        w = "Watch for repeat filings, planning milestones and unit-count changes; those show whether activity is becoming a durable pipeline."
    elif key == "service_requests":
        h = "Why 311 can move suddenly"
        a = f"311 volume is {mag}{direction} its recent weekly average. The feed measures both conditions and residents' willingness to report them, so construction, city operations, a concentrated nuisance or a reporting campaign can move the number quickly."
        w = "Watch whether the same request type persists and clusters around a project, corridor or public-space change."
    else:
        h = "Why the public-safety number needs context"
        a = f"Reported incidents are {mag}{direction} the recent weekly average. At neighborhood scale, a few incidents or a change in reporting can materially shift a seven-day percentage, so the eight-week pulse and incident mix matter more than one headline number."
        w = "Watch whether the same incident category persists across multiple weeks before treating the move as a neighborhood trend."
    if cov:
        a += " Recent local reporting offers a possible explanation or backdrop below, but timing alone is not treated as proof of causation."
    return {"headline": h, "analysis": a, "watch": w, "coverage": cov, "signal_score": signal_score(e), "signal_reason": significance_reason(e)}


def city_metric(snapshot, key):
    ms = [e.get("metrics", {}).get(key) for e in snapshot.get("editions", {}).values()]
    ms = [m for m in ms if m]
    cur = sum(m.get("current", 0) for m in ms)
    base = sum(float(m.get("baseline_week", 0)) for m in ms)
    pct = ((cur - base) / base * 100) if base >= 1 else None
    return {"current": cur, "baseline_week": round(base, 1), "pct_change": round(pct, 1) if pct is not None else None}


def top_hoods(snapshot, key):
    rows = []
    for e in snapshot.get("editions", {}).values():
        m = e.get("metrics", {}).get(key)
        if not m:
            continue
        d = m.get("current", 0) - float(m.get("baseline_week", 0))
        rows.append({
            "name": e["name"],
            "slug": e["slug"],
            "current": m.get("current", 0),
            "delta": round(d, 1),
            "pct_change": m.get("pct_change"),
            "signal_score": signal_score(e, key),
            "signal_reason": significance_reason(e, key),
        })
    return sorted(rows, key=lambda x: (x["signal_score"], abs(x["delta"])), reverse=True)[:4]


def theme_coverage(key, top, items, now):
    top_names = {x["name"] for x in top}
    scored = []
    for item in items:
        if item.get("beat") != key or not recent(item, now):
            continue
        targets = set(item.get("target_neighborhoods") or [])
        body = norm((item.get("title") or "") + " " + (item.get("summary") or ""))
        local_hits = sum(1 for name in top_names if any(norm(a) in body for a in aliases(name)))
        score = (14 if targets & top_names else 0) + local_hits * 6 + max(0, 4 - (now - published(item)).days / 7)
        scored.append((score, published(item), item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    chosen = []
    seen_articles = set()
    seen_publishers = set()
    for _, _, item in scored:
        key_id = article_key(item)
        pub = norm(item.get("publisher"))
        if not key_id or key_id in seen_articles or (pub and pub in seen_publishers):
            continue
        chosen.append(item)
        seen_articles.add(key_id)
        if pub:
            seen_publishers.add(pub)
        if len(chosen) >= 3:
            break
    return chosen


def city_theme(snapshot, key, items, now):
    m = city_metric(snapshot, key)
    pct = m.get("pct_change")
    d = "up" if pct is not None and pct > 8 else ("down" if pct is not None and pct < -8 else "roughly flat")
    top = top_hoods(snapshot, key)
    names = ", ".join(x["name"] for x in top[:3]) or "several neighborhoods"
    why = {
        "businesses": "Registrations mix real storefront momentum with administrative churn. Repeated corridor activity plus reporting on leases, grants, vacancies or foot traffic helps explain whether the change is durable.",
        "permits": "Financing costs, zoning changes, project redesigns and office-to-housing efforts are shaping the development cycle. Unit-adding filings and large milestones matter more than raw permit volume.",
        "service_requests": "311 reacts to construction, public-space work, enforcement and reporting behavior. Persistent category changes across several neighborhoods are stronger evidence than a one-week spike.",
        "police": "Reported incidents can move differently by category and neighborhood. Small weekly counts are volatile, so citywide direction and multi-week persistence provide the best context.",
    }[key]
    headline = {
        "businesses": f"Business registrations are {d}; the strongest signals are in {names}",
        "permits": f"Development filings are {d}; the most consequential activity is in {names}",
        "service_requests": f"311 activity is {d}; the most significant departures are in {names}",
        "police": f"Reported incidents are {d}; {names} have the strongest current signals",
    }[key]
    return {"key": key, "label": BEATS[key], "headline": headline, "why": why, "metric": m, "neighborhoods": top, "coverage": theme_coverage(key, top, items, now)}


def enrich_snapshot(snapshot, items, generated_at=None):
    now = generated_at or datetime.now(timezone.utc)
    coverage_map = assign_coverage(snapshot, items, now)
    for e in snapshot.get("editions", {}).values():
        e["editorial"] = why_for(e, coverage_map.get(e["slug"], []))

    themes = [city_theme(snapshot, k, items, now) for k in ("businesses", "permits", "service_requests", "police")]
    strongest = sorted(
        themes,
        key=lambda t: max((x.get("signal_score", 0) for x in t.get("neighborhoods", [])), default=0),
        reverse=True,
    )
    summary = (
        f"The strongest citywide public-record signal this week is {strongest[0]['label'].lower()}. The city page now prioritizes consequential neighborhood changes, then matches them to targeted recent reporting without recycling the same article across multiple crossovers."
        if strongest
        else "The city page connects the strongest neighborhood signals with recent reporting to explain what may be driving the numbers."
    )

    cross = []
    used_articles = set()
    ranked_editions = sorted(snapshot.get("editions", {}).values(), key=signal_score, reverse=True)
    for e in ranked_editions:
        cov = e.get("editorial", {}).get("coverage", [])
        score = signal_score(e)
        if score < 52 or not cov or not e.get("lead"):
            continue
        primary = next((item for item in cov if article_key(item) not in used_articles), None)
        if not primary:
            continue
        used_articles.add(article_key(primary))
        cross.append({
            "name": e["name"],
            "slug": e["slug"],
            "headline": e["lead"]["headline"],
            "section": e["lead"]["section"],
            "article": primary,
            "interest": e["lead"].get("interest", 0),
            "signal_score": score,
            "signal_reason": significance_reason(e),
        })
        if len(cross) >= 8:
            break

    recent_items = [x for x in items if recent(x, now)]
    snapshot["city_analysis"] = {
        "summary": summary,
        "themes": themes,
        "crossovers": cross,
        "news_count": len(recent_items),
        "targeted_news_count": len([x for x in recent_items if x.get("target_neighborhoods")]),
    }
    snapshot["news_context"] = {
        "updated_at": now.isoformat(),
        "items_considered": len(items),
        "recent_items": len(recent_items),
        "targeted_items": len([x for x in items if x.get("target_neighborhoods")]),
        "method": "Broad city searches plus targeted searches generated from the strongest DataSF neighborhood signals; crossover articles are globally de-duplicated.",
    }
    return snapshot
