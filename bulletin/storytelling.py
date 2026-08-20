from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any


SOURCE_LABELS = {
    "businesses": "Business",
    "permits": "Development",
    "service_requests": "City services",
    "police": "Public safety",
}


def _text(value: Any, limit: int = 220) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip(" ,;:-") + "…"


def _money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if amount >= 10_000_000:
        return f"${amount / 1_000_000:.0f} million"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f} million"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}" if amount else ""


def _variant(hood: str, source: str, generated_at: datetime, size: int) -> int:
    # The morning/evening refresh slot is part of the key. This lets wording evolve
    # between editions without introducing randomness or changing any underlying fact.
    slot = "am" if generated_at.hour < 14 else "pm"
    key = f"{generated_at.date().isoformat()}|{slot}|{hood}|{source}".encode()
    return int(hashlib.sha1(key).hexdigest()[:8], 16) % max(1, size)


def _change_phrase(metric: dict) -> str:
    current = int(metric.get("current") or 0)
    baseline = float(metric.get("baseline_week") or 0)
    pct = metric.get("pct_change")
    if pct is None:
        return f"{current} in the latest seven-day window, versus a recent weekly average of {baseline:.1f}"
    if abs(float(pct)) < 8:
        return f"{current} in the latest seven days, roughly level with the recent weekly average"
    direction = "above" if float(pct) > 0 else "below"
    return f"{current} in the latest seven days, {abs(float(pct)):.0f}% {direction} the prior four-week weekly average"


def _top_category(metric: dict) -> dict:
    return next((x for x in (metric.get("categories") or []) if (x.get("current") or 0) > 0), {})


def _prior_story(prior: dict | None, slug: str, source: str) -> dict:
    if not prior:
        return {}
    return ((prior.get("editions") or {}).get(slug) or {}).get("metrics", {}).get(source, {}) or {}


def _refresh_note(metric: dict, prior_metric: dict) -> str:
    if not prior_metric:
        return "First comparison available in this browser-visible edition."
    current = int(metric.get("current") or 0)
    previous = int(prior_metric.get("current") or 0)
    current_latest = str(metric.get("latest") or "")[:10]
    prior_latest = str(prior_metric.get("latest") or "")[:10]
    delta = current - previous
    if current_latest and prior_latest and current_latest != prior_latest:
        if delta:
            return f"Source advanced from {prior_latest} to {current_latest}; the seven-day count changed by {delta:+d}."
        return f"Source advanced from {prior_latest} to {current_latest}; the seven-day count is unchanged."
    if delta:
        return f"Since the prior Bulletin refresh, the seven-day count changed by {delta:+d}."
    return "The underlying seven-day count is unchanged since the prior Bulletin refresh; reporting and context may still be newer."


def _search_fields(source: str, hood: str, records: list[dict], metric: dict) -> dict[str, str]:
    first = records[0] if records else {}
    address = _text(first.get("address"), 140)
    if source == "businesses":
        name = _text(first.get("title"), 120)
        exact = f'"{address}" "{name}" San Francisco' if address and name else f'"{name or hood}" San Francisco business'
        return {
            "search_query": exact,
            "news_query": f'{exact} opening storefront restaurant retail business',
            "maps_query": f"{address}, San Francisco" if address else f"{name} San Francisco",
        }
    if source == "permits":
        permit = _text(first.get("permit_number"), 50)
        exact = f'"{address}" San Francisco' if address else f'"{hood}" San Francisco development'
        if permit:
            exact += f' "{permit}"'
        return {
            "search_query": f"{exact} building permit",
            "news_query": f'{exact} housing development construction planning',
            "maps_query": f"{address}, San Francisco" if address else f"{hood}, San Francisco",
        }
    if source == "service_requests":
        category = _text(first.get("category") or first.get("title") or _top_category(metric).get("display_category"), 100)
        exact = f'"{address}" San Francisco' if address else f'"{hood}" San Francisco'
        return {
            "search_query": f'{exact} "{category}" 311 city services',
            "news_query": f'{exact} {category} public works neighborhood',
            "maps_query": f"{address}, San Francisco" if address else f"{hood}, San Francisco",
        }
    if source == "police":
        category = _text(first.get("category") or _top_category(metric).get("display_category") or "police", 100)
        intersection = address
        exact = f'"{intersection}" San Francisco' if intersection else f'"{hood}" San Francisco'
        return {
            "search_query": f'{exact} SFPD "{category}"',
            "news_query": f'{exact} SFPD police {category}',
            "maps_query": "",
        }
    return {
        "search_query": f'"{hood}" San Francisco',
        "news_query": f'"{hood}" San Francisco neighborhood',
        "maps_query": f"{hood}, San Francisco",
    }


def _business_story(hood: str, story: dict, metric: dict, records: list[dict], variant: int) -> tuple[str, str, str, list[str]]:
    n = int(metric.get("current") or 0)
    first = records[0] if records else {}
    name = _text(first.get("title"), 100)
    address = _text(first.get("address"), 120)
    owner = _text(first.get("owner"), 100)
    headlines = [
        f"{name} lands on {hood}'s latest business ledger" if name else f"A closer look at {hood}'s newest business registrations",
        f"A new business filing puts {name} at {address}" if name and address else f"What just appeared on {hood}'s business ledger",
        f"At {address}, a new registration names {name}" if name and address else f"The names behind {hood}'s latest business filings",
        f"{hood}'s business ledger added {n} location registration{'s' if n != 1 else ''}" if n else f"Reading {hood}'s latest business ledger",
    ]
    color = []
    for item in records[:3]:
        label = _text(item.get("title"), 100)
        place = _text(item.get("address"), 100)
        if label:
            color.append(f"{label}{f' — {place}' if place else ''}")
    if owner and name and owner.lower() != name.lower():
        color.append(f"Registered owner: {owner}")
    dek = f"The current business-location feed shows {_change_phrase(metric)}."
    if name and address:
        dek += f" The newest named filing lists {name} at {address}; a registration is a location filing, not confirmation that a storefront has opened."
    hook = "Watch the address, not just the count: repeat filings along the same corridor are more revealing than a single registration burst."
    return headlines[variant], dek, hook, color[:4]


def _permit_story(hood: str, story: dict, metric: dict, records: list[dict], variant: int) -> tuple[str, str, str, list[str]]:
    first = records[0] if records else {}
    housing = next((x for x in records if (x.get("unit_delta") or 0) > 0), None)
    focus = housing or first
    address = _text(focus.get("address"), 120)
    scope = _text(focus.get("scope_summary") or focus.get("description") or focus.get("title"), 135)
    value = _money(focus.get("cost"))
    unit_delta = int(focus.get("unit_delta") or 0)
    if housing and address:
        headlines = [
            f"Inside the {address} filing: {unit_delta} net new home{'s' if unit_delta != 1 else ''} proposed",
            f"A permit at {address} would add {unit_delta} housing unit{'s' if unit_delta != 1 else ''}",
            f"{address} moves onto the housing watch list with a {unit_delta}-unit increase",
            f"The housing detail inside {hood}'s latest permit filings",
        ]
    elif address and value:
        headlines = [
            f"{value} of work is on file at {address}",
            f"Inside the permit at {address}: a {value} project",
            f"A larger filing at {address} stands out in {hood}",
            f"What the {address} permit says is changing",
        ]
    elif address:
        headlines = [
            f"What the latest permit at {address} actually proposes",
            f"Inside {address}'s newest building filing",
            f"A new filing puts {address} on {hood}'s development ledger",
            f"The street-level detail behind {hood}'s permit count",
        ]
    else:
        headlines = [
            f"What is moving through {hood}'s development pipeline",
            f"Reading between the lines of {hood}'s newest permits",
            f"The projects behind {hood}'s latest permit count",
            f"A street-level look at development filings in {hood}",
        ]
    color = []
    if address:
        color.append(address)
    if scope:
        color.append(scope)
    if value:
        color.append(f"Listed project value: {value}")
    if focus.get("status_summary") or focus.get("status"):
        color.append(f"Status: {_text(focus.get('status_summary') or focus.get('status'), 100)}")
    dek = f"Permit filings show {_change_phrase(metric)}."
    if scope:
        dek += f" The filing to read is at {address or hood}: {scope}"
    hook = "The useful signal is project substance—scope, unit count, use and status—not the raw number of permits alone."
    return headlines[variant], dek, hook, color[:4]


def _service_story(hood: str, story: dict, metric: dict, records: list[dict], variant: int) -> tuple[str, str, str, list[str]]:
    top = _top_category(metric)
    category = _text(top.get("display_category") or top.get("category") or "311 requests", 90)
    cur = int(top.get("current") or 0)
    headlines = [
        f"What {hood} residents are calling 311 about right now",
        f"{category.capitalize()} is shaping {hood}'s latest 311 mix",
        f"The street-level complaints behind {hood}'s 311 numbers",
        f"A closer look at the {cur} {category.lower()} requests in {hood}" if cur else f"Inside {hood}'s latest city-service requests",
    ]
    color = []
    seen = set()
    for item in records[:4]:
        label = _text(item.get("title"), 95)
        address = _text(item.get("address"), 95)
        line = f"{label}{f' — {address}' if address else ''}" if label else address
        if line and line.lower() not in seen:
            seen.add(line.lower())
            color.append(line)
    dek = f"The latest 311 feed shows {_change_phrase(metric)}."
    if category:
        dek += f" {category.capitalize()} is the most active visible category, with {cur} request{'s' if cur != 1 else ''}."
    hook = "311 measures both conditions and reporting behavior. Repeated requests on the same block or corridor are usually more informative than a citywide percentage swing."
    return headlines[variant], dek, hook, color[:4]


def _police_story(hood: str, story: dict, metric: dict, records: list[dict], variant: int) -> tuple[str, str, str, list[str]]:
    top = _top_category(metric)
    category = _text(top.get("display_category") or top.get("category") or "reported incidents", 90)
    n = int(metric.get("current") or 0)
    headlines = [
        f"What the latest SFPD filings show in {hood}",
        f"{category} leads {hood}'s newest SFPD report mix",
        f"Inside {hood}'s latest {n} police report{'s' if n != 1 else ''}",
        f"The incident mix behind {hood}'s newest public-safety numbers",
    ]
    color = []
    for item in records[:3]:
        title = _text(item.get("title"), 95)
        place = _text(item.get("address"), 100)
        reported = _text(item.get("reported_display"), 80)
        line = title
        if place:
            line += f" — near {place}"
        if reported:
            line += f" · reported {reported}"
        if line:
            color.append(line)
    dek = f"SFPD report filings show {_change_phrase(metric)}."
    if category:
        dek += f" {category} is the largest category in the current seven-day filing window."
    hook = "At neighborhood scale, a handful of filings can move percentages quickly. The mix of report types and persistence across weeks matter more than a single spike."
    return headlines[variant], dek, hook, color[:4]


def enrich_storytelling(snapshot: dict, previous_snapshot: dict | None, generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    for slug, edition in (snapshot.get("editions") or {}).items():
        hood = edition.get("name") or slug
        refresh_changes = []
        for story in edition.get("stories") or []:
            source = story.get("source")
            metric = (edition.get("metrics") or {}).get(source) or {}
            records = (edition.get("notable") or {}).get(source) or []
            prior_metric = _prior_story(previous_snapshot, slug, source)
            change_note = _refresh_note(metric, prior_metric)
            refresh_changes.append({
                "source": source,
                "label": SOURCE_LABELS.get(source, source),
                "note": change_note,
                "changed": change_note.startswith("Source advanced") or "changed by" in change_note,
            })

            if source == "businesses":
                headline, dek, hook, color = _business_story(hood, story, metric, records, _variant(hood, source, generated_at, 4))
            elif source == "permits":
                headline, dek, hook, color = _permit_story(hood, story, metric, records, _variant(hood, source, generated_at, 4))
            elif source == "service_requests":
                headline, dek, hook, color = _service_story(hood, story, metric, records, _variant(hood, source, generated_at, 4))
            elif source == "police":
                headline, dek, hook, color = _police_story(hood, story, metric, records, _variant(hood, source, generated_at, 4))
            else:
                continue

            story["headline"] = _text(headline, 165)
            story["dek"] = _text(dek, 430)
            story["reader_hook"] = _text(hook, 300)
            story["color_items"] = color
            story["refresh_note"] = change_note
            story.update(_search_fields(source, hood, records, metric))

        edition["refresh_changes"] = refresh_changes
        # Lead points at one of the story dicts in normal snapshot construction, but
        # repair it explicitly in case a persisted snapshot was deserialized first.
        lead_source = (edition.get("lead") or {}).get("source")
        if lead_source:
            matching = next((x for x in edition.get("stories") or [] if x.get("source") == lead_source), None)
            if matching:
                edition["lead"] = matching

    # front_page contains copies, so merge the enriched edition story fields back in.
    refreshed_front = []
    for item in snapshot.get("front_page") or []:
        edition = (snapshot.get("editions") or {}).get(item.get("slug")) or {}
        source = item.get("source")
        match = next((x for x in edition.get("stories") or [] if x.get("source") == source), None)
        refreshed_front.append({**item, **(match or {})})
    snapshot["front_page"] = refreshed_front
    snapshot["storytelling"] = {
        "edition_slot": "morning" if generated_at.hour < 14 else "evening",
        "generated_at": generated_at.isoformat(),
        "note": "Headline structures rotate by edition while remaining grounded in the same public records.",
    }
    return snapshot


def build_live_digest(snapshot: dict, news_items: list[dict], previous_snapshot: dict | None, generated_at: datetime) -> list[dict]:
    previous_news_time = (((previous_snapshot or {}).get("news_context") or {}).get("updated_at"))
    try:
        prior_dt = datetime.fromisoformat(str(previous_news_time).replace("Z", "+00:00")) if previous_news_time else None
        if prior_dt and prior_dt.tzinfo is None:
            prior_dt = prior_dt.replace(tzinfo=timezone.utc)
    except Exception:
        prior_dt = None

    candidates = []
    for item in news_items:
        try:
            published = datetime.fromisoformat(str(item.get("published") or "").replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        age_hours = max(0.0, (generated_at - published).total_seconds() / 3600)
        if age_hours > 96:
            continue
        neighborhoods = item.get("local_verified_neighborhoods") or item.get("neighborhoods") or item.get("target_neighborhoods") or []
        if not neighborhoods:
            continue
        publisher = _text(item.get("publisher"), 80)
        score = max(0, 48 - age_hours / 2)
        if item.get("local_verified_neighborhoods"):
            score += 18
        if item.get("live"):
            score += 5
        candidates.append((score, published, {
            **item,
            "digest_neighborhood": neighborhoods[0],
            "is_new_refresh": bool(prior_dt and published > prior_dt),
            "age_hours": round(age_hours, 1),
            "publisher": publisher,
        }))

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    chosen = []
    used_titles = set()
    publisher_counts: dict[str, int] = {}
    hood_counts: dict[str, int] = {}
    for _, _, item in candidates:
        title_key = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").lower()).strip()
        publisher_key = str(item.get("publisher") or "").lower()
        hood = item.get("digest_neighborhood") or ""
        if not title_key or title_key in used_titles:
            continue
        if publisher_counts.get(publisher_key, 0) >= 2 or hood_counts.get(hood, 0) >= 2:
            continue
        chosen.append(item)
        used_titles.add(title_key)
        publisher_counts[publisher_key] = publisher_counts.get(publisher_key, 0) + 1
        hood_counts[hood] = hood_counts.get(hood, 0) + 1
        if len(chosen) >= 8:
            break
    return chosen
