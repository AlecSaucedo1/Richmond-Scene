from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")


def _text(value: Any, limit: int = 520) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip(" ,;:-") + "…"


def _money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if not amount:
        return ""
    if amount >= 1_000_000:
        return "$" + f"{amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return "$" + f"{amount / 1_000:.0f}K"
    return "$" + f"{amount:,.0f}"


def _metric_sentence(metric: dict, label: str) -> str:
    current = int(metric.get("current") or 0)
    baseline = float(metric.get("baseline_week") or 0)
    pct = metric.get("pct_change")
    if pct is None:
        return f"{label} logged {current} records in the latest seven-day window, versus a recent weekly average of {baseline:.1f}."
    pct = float(pct)
    if abs(pct) < 8:
        return f"{label} logged {current} records, roughly in line with the recent four-week weekly average."
    direction = "above" if pct > 0 else "below"
    return f"{label} logged {current} records, {abs(pct):.0f}% {direction} the recent four-week weekly average."


def _variant(slug: str, day: str, size: int) -> int:
    key = f"{day}|{slug}".encode()
    return int(hashlib.sha1(key).hexdigest()[:8], 16) % max(1, size)


def _top_category(metric: dict) -> str:
    for item in metric.get("categories") or []:
        name = _text(item.get("display_category") or item.get("category"), 100)
        if name and (item.get("current") or 0):
            return name
    return ""


def _sale_context(snapshot: dict, slug: str) -> str:
    desk = ((snapshot.get("real_estate") or {}).get("neighborhoods") or {}).get(slug) or {}
    sales = list(desk.get("residential") or []) + list(desk.get("commercial") or [])
    if not sales:
        return ""
    sale = max(sales, key=lambda item: float(item.get("sale_price") or 0))
    address = _text(sale.get("address_line") or sale.get("address"), 140)
    price = _money(sale.get("sale_price"))
    kind = _text(sale.get("property_type") or sale.get("property_group") or "property", 80)
    date = _text(sale.get("sale_date") or sale.get("recorded_date"), 40)
    if not address:
        return ""
    parts = [f"The property tape adds a separate market signal at {address}"]
    if price:
        parts.append(f"where the published transaction price is {price}")
    if kind:
        parts.append(f"for a {kind.lower()}")
    sentence = ", ".join(parts) + "."
    if date:
        sentence += f" The source lists the transaction date as {date}."
    sentence += " A recorded transfer is useful context, but it is not necessarily an arm's-length market sale."
    return sentence


def _arts_context(snapshot: dict, neighborhood: str) -> str:
    desk = ((snapshot.get("arts") or {}).get("neighborhoods") or {}).get(neighborhood) or {}
    exhibits = desk.get("exhibitions") or []
    events = desk.get("events") or []
    if exhibits:
        item = exhibits[0]
        title = _text(item.get("title"), 160)
        museum = _text(item.get("museum"), 100)
        if title:
            return f"Neighborhood activity is not only administrative. {museum + ' is showing ' if museum else 'The current arts calendar includes '}{title}, adding a cultural draw that sits outside the public-record trend lines but still shapes why people come to the area."
    if events:
        item = events[0]
        title = _text(item.get("title"), 160)
        venue = _text(item.get("venue"), 100)
        if title:
            return f"The current cultural calendar adds another reason for foot traffic: {title}{' at ' + venue if venue else ''}. That does not explain changes in permits, registrations or service requests, but it is part of the neighborhood context readers actually experience."
    return ""


def _dining_context(snapshot: dict, neighborhood: str) -> str:
    matches = []
    for item in snapshot.get("restaurant_reviews") or []:
        if neighborhood in (item.get("verified_neighborhoods") or []):
            matches.append(item)
    if not matches:
        return ""
    matches.sort(key=lambda item: str(item.get("published") or ""), reverse=True)
    item = matches[0]
    title = _text(item.get("title"), 180)
    publisher = _text(item.get("publisher"), 90)
    if not title:
        return ""
    return f"Recent dining coverage adds a more human-scale layer to the ledger. {publisher + ' recently published ' if publisher else 'Recent reporting includes '}{title}. The Bulletin treats that article as neighborhood context, not evidence that any public-record movement caused the restaurant story."


def _reporting_context(edition: dict) -> str:
    coverage = ((edition.get("editorial") or {}).get("coverage") or [])
    if not coverage:
        return ""
    item = coverage[0]
    title = _text(item.get("title"), 190)
    publisher = _text(item.get("publisher"), 90)
    summary = _text(item.get("summary"), 320)
    if not title:
        return ""
    sentence = f"Independent reporting is another check on the numbers. {publisher + ' reported ' if publisher else 'A recent local report is '}{title}."
    if summary:
        sentence += f" {summary}"
    sentence += " It provides context around the neighborhood, but the Bulletin does not treat overlap in timing as proof of causation."
    return sentence


def _participants_context(edition: dict) -> str:
    participants = edition.get("permit_market_participants") or {}
    owners = participants.get("owners") or []
    contractors = participants.get("general_contractors") or []
    repeat_owners = [item for item in owners if item.get("repeat_participant")]
    repeat_contractors = [item for item in contractors if item.get("repeat_participant")]
    lines = []
    if repeat_owners:
        item = repeat_owners[0]
        lines.append(f"{_text(item.get('name'), 100)} appears on {item.get('filings') or 0} neighborhood permit filings and {item.get('citywide_filings') or 0} citywide filings in the current contact window")
    if repeat_contractors:
        item = repeat_contractors[0]
        lines.append(f"{_text(item.get('name'), 100)} appears as a contractor contact on {item.get('filings') or 0} neighborhood filings and {item.get('citywide_filings') or 0} citywide")
    if not lines:
        return ""
    return "The names behind the permits are beginning to offer another way to read the market. " + "; ".join(lines) + ". These are DBI permit-contact roles and distinct filing counts, not ownership-market-share estimates."


def _permit_context(edition: dict) -> str:
    records = (edition.get("notable") or {}).get("permits") or []
    if not records:
        return ""
    item = records[0]
    address = _text(item.get("address") or item.get("title"), 140)
    scope = _text(item.get("scope_summary") or item.get("description") or item.get("title"), 420)
    value = _money(item.get("cost"))
    units = item.get("unit_delta")
    owner = _text(item.get("owner"), 110)
    contractor = _text(item.get("general_contractor"), 110)
    parts = [f"The clearest physical-change signal is the filing at {address}." if address else "The clearest physical-change signal is the neighborhood's leading permit filing."]
    if scope:
        parts.append(scope)
    if value:
        parts.append(f"The filing lists a project value of {value}.")
    if units:
        parts.append(f"It proposes a net change of {int(units):+d} housing unit{'s' if abs(int(units)) != 1 else ''}.")
    if owner:
        parts.append(f"DBI lists {owner} in the owner role.")
    if contractor:
        parts.append(f"{contractor} is the listed general-contractor contact.")
    parts.append("A permit filing is a proposal in the record, not confirmation that the project has been approved or completed.")
    return " ".join(parts)


def _business_context(edition: dict) -> str:
    records = (edition.get("notable") or {}).get("businesses") or []
    if not records:
        return ""
    names = []
    for item in records[:3]:
        name = _text(item.get("title"), 110)
        address = _text(item.get("address"), 120)
        if name:
            names.append(name + (f" at {address}" if address else ""))
    if not names:
        return ""
    return "On the commercial side, the newest location records include " + "; ".join(names) + ". A location registration is evidence of administrative business activity at an address; it is not, by itself, confirmation that a storefront has opened."


def _civic_context(edition: dict) -> str:
    metrics = edition.get("metrics") or {}
    service = metrics.get("service_requests") or {}
    police = metrics.get("police") or {}
    service_cat = _top_category(service)
    police_cat = _top_category(police)
    sentence = _metric_sentence(service, "311 requests") + " " + _metric_sentence(police, "SFPD reports filed")
    if service_cat:
        sentence += f" {service_cat} is the leading visible 311 category."
    if police_cat:
        sentence += f" {police_cat} is the leading visible SFPD filing category."
    sentence += " These two feeds require different caution: 311 reflects both service demand and reporting behavior, while police reports filed are not a crime rate or a measure of neighborhood safety."
    return sentence


def _headline(edition: dict, day: str) -> str:
    hood = edition.get("name") or "the neighborhood"
    lead = edition.get("lead") or {}
    permit = ((edition.get("notable") or {}).get("permits") or [{}])[0]
    business = ((edition.get("notable") or {}).get("businesses") or [{}])[0]
    address = _text(permit.get("address"), 80)
    biz = _text(business.get("title"), 80)
    choices = [
        f"Reading {hood} as one neighborhood, not four separate data feeds",
        f"What the week's permits, storefront filings and street requests say about {hood}",
        f"The signals moving together — and apart — across {hood}",
        f"A daily read on what is changing around {hood}",
    ]
    if address and biz:
        choices.append(f"From {address} to {biz}: two clues in {hood}'s changing ledger")
    if lead.get("headline"):
        choices.append(f"Beyond the headline: how today's signals fit together in {hood}")
    return choices[_variant(edition.get("slug") or hood, day, len(choices))]


def build_long_read(snapshot: dict, slug: str, edition: dict, day: str) -> dict:
    metrics = edition.get("metrics") or {}
    paragraphs = []

    lead = edition.get("lead") or {}
    lead_dek = _text(lead.get("dek"), 520)
    intro_choices = [
        f"Neighborhood data is most useful when it is read as a set of overlapping clues rather than a scoreboard. In {edition.get('name')}, today's strongest signal is {lead_dek[:1].lower() + lead_dek[1:] if lead_dek else 'a mix of public-record activity across several beats'}. The rest of the ledger complicates that first impression in useful ways.",
        f"The headline number rarely tells the whole neighborhood story. {lead_dek} Read beside the permit ledger, business registrations, service requests, property activity and local reporting, it becomes one part of a broader picture of where attention and investment are showing up.",
        f"A neighborhood changes through many small administrative acts before those changes are obvious on the street: a permit is filed, a business location is registered, a service request is logged, a property changes hands. {edition.get('name')}'s current Bulletin brings enough of those signals together to look for patterns without pretending they share a single cause.",
    ]
    paragraphs.append(intro_choices[_variant(slug + "-intro", day, len(intro_choices))])

    paragraphs.append(
        "The baseline matters first. "
        + _metric_sentence(metrics.get("businesses") or {}, "Business-location registrations") + " "
        + _metric_sentence(metrics.get("permits") or {}, "Building permit filings") + " "
        + _metric_sentence(metrics.get("service_requests") or {}, "311 requests") + " "
        + _metric_sentence(metrics.get("police") or {}, "SFPD reports filed")
        + " The four measures describe different systems, so the value is in their direction, persistence and street-level detail rather than in combining them into one score."
    )

    for context in (_permit_context(edition), _participants_context(edition), _business_context(edition), _civic_context(edition)):
        if context:
            paragraphs.append(context)

    context_paragraphs = [
        _sale_context(snapshot, slug),
        _reporting_context(edition),
        _dining_context(snapshot, edition.get("name") or ""),
        _arts_context(snapshot, edition.get("name") or ""),
    ]
    context_paragraphs = [item for item in context_paragraphs if item]
    if context_paragraphs:
        paragraphs.append(" ".join(context_paragraphs[:2]))
    if len(context_paragraphs) > 2:
        paragraphs.append(" ".join(context_paragraphs[2:]))

    editorial = edition.get("editorial") or {}
    analysis = _text(editorial.get("analysis"), 700)
    signal_reason = _text(editorial.get("signal_reason"), 360)
    if analysis or signal_reason:
        paragraphs.append(
            (f"The Bulletin's existing neighborhood analysis adds one more layer. {analysis} " if analysis else "")
            + (f"The reason this signal is worth watching is {signal_reason[:1].lower() + signal_reason[1:] if signal_reason else ''} " if signal_reason else "")
            + "The interpretation remains provisional: a short public-record window can identify concentration and change, but it cannot by itself establish why the change occurred."
        )

    watch = _text(editorial.get("watch"), 480)
    paragraphs.append(
        "The next edition should be judged less by whether today's percentage becomes larger and more by whether the same addresses, categories and market participants keep resurfacing. "
        + (watch if watch else "Watch for persistence in the leading permit and business records, repeated activity on the same corridors, and whether independent reporting adds context to the public-record pattern.")
        + " This long read refreshes once each San Francisco calendar day so the narrative can evolve at a slower pace than the twice-daily headline tape."
    )

    word_count = len(" ".join(paragraphs).split())
    signals = []
    if (edition.get("notable") or {}).get("permits"):
        signals.append("Building permits")
    if (edition.get("notable") or {}).get("businesses"):
        signals.append("Business registrations")
    signals.extend(["311 requests", "SFPD reports filed"])
    if _participants_context(edition):
        signals.append("Permit market participants")
    if _sale_context(snapshot, slug):
        signals.append("Real estate transactions")
    if _reporting_context(edition):
        signals.append("Recent local reporting")
    if _dining_context(snapshot, edition.get("name") or ""):
        signals.append("Dining coverage")
    if _arts_context(snapshot, edition.get("name") or ""):
        signals.append("Arts & culture")

    watchlist = [
        "Whether the leading seven-day signal persists rather than reverting toward its recent baseline",
        "Whether the same permit owners or general contractors appear on additional neighborhood filings",
        "Whether business-location registrations cluster along the same commercial corridors",
        "Whether new reporting, transactions or cultural activity add context to the public-record pattern",
    ]

    return {
        "slug": slug,
        "headline": _headline(edition, day),
        "dek": f"A once-daily synthesis connecting the records, market participants and local context shaping {edition.get('name')} now.",
        "body": paragraphs,
        "watchlist": watchlist,
        "signals_connected": signals[:8],
        "generated_for": day,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "word_count": word_count,
        "reading_minutes": max(3, math.ceil(word_count / 210)),
        "method": "deterministic-source-synthesis",
    }


def build_daily_long_reads(snapshot: dict, previous_snapshot: dict | None = None) -> dict:
    day = datetime.now(PACIFIC).date().isoformat()
    previous_reads = (previous_snapshot or {}).get("long_reads") or {}
    previous_meta = (previous_snapshot or {}).get("long_read_meta") or {}

    if previous_reads and previous_meta.get("generated_for") == day:
        snapshot["long_reads"] = previous_reads
        snapshot["long_read_meta"] = {
            **previous_meta,
            "reused_at": datetime.now(timezone.utc).isoformat(),
            "reused_for_same_day": True,
        }
        return snapshot

    reads = {
        slug: build_long_read(snapshot, slug, edition, day)
        for slug, edition in (snapshot.get("editions") or {}).items()
    }
    snapshot["long_reads"] = reads
    snapshot["long_read_meta"] = {
        "generated_for": day,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "neighborhood_count": len(reads),
        "refresh_policy": "Once per America/Los_Angeles calendar day; morning/evening refreshes reuse the day's article.",
        "method": "Deterministic synthesis from the Bulletin's current public-record, reporting, real-estate, dining and arts context.",
    }
    return snapshot
