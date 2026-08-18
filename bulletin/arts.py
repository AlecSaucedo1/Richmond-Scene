from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import httpx


MUSEUM_SOURCES = (
    {"name": "SFMOMA", "neighborhood": "South of Market", "address": "151 Third St", "url": "https://www.sfmoma.org/exhibitions/"},
    {"name": "de Young", "neighborhood": "Golden Gate Park", "address": "50 Hagiwara Tea Garden Dr", "url": "https://www.famsf.org/exhibitions"},
    {"name": "Legion of Honor", "neighborhood": "Lincoln Park", "address": "100 34th Ave", "url": "https://www.famsf.org/exhibitions"},
    {"name": "Asian Art Museum", "neighborhood": "Tenderloin", "address": "200 Larkin St", "url": "https://calendar.asianart.org/"},
    {"name": "Museum of the African Diaspora", "neighborhood": "South of Market", "address": "685 Mission St", "url": "https://www.moadsf.org/exhibitions"},
    {"name": "Yerba Buena Center for the Arts", "neighborhood": "South of Market", "address": "701 Mission St", "url": "https://ybca.org/"},
)

VENUE_SOURCES = (
    {"name": "SFJAZZ Center", "neighborhood": "Hayes Valley", "category": "Music", "url": "https://www.sfjazz.org/tickets/productions/"},
    {"name": "Davies Symphony Hall", "neighborhood": "Hayes Valley", "category": "Music", "url": "https://www.sfsymphony.org/"},
    {"name": "War Memorial Opera House", "neighborhood": "Hayes Valley", "category": "Opera", "url": "https://www.sfopera.com/whats-on/"},
    {"name": "The Fillmore", "neighborhood": "Western Addition", "category": "Music", "url": "https://www.livenation.com/venue/KovZpZA6ta1A/the-fillmore-events"},
    {"name": "Great American Music Hall", "neighborhood": "Tenderloin", "category": "Music", "url": "https://gamh.com/calendar/"},
    {"name": "The Independent", "neighborhood": "Western Addition", "category": "Music", "url": "https://theindependentsf.com/"},
    {"name": "Chase Center", "neighborhood": "Mission Bay", "category": "Music", "url": "https://www.chasecenter.com/events"},
    {"name": "Palace of Fine Arts", "neighborhood": "Marina", "category": "Culture", "url": "https://palaceoffinearts.com/events/"},
    {"name": "Yerba Buena Center for the Arts", "neighborhood": "South of Market", "category": "Culture", "url": "https://ybca.org/"},
)

# Current official-program entries provide a resilient baseline if a venue blocks a
# scrape or changes markup. They automatically disappear when their end date passes.
EXHIBITION_SEEDS = (
    {"museum": "SFMOMA", "neighborhood": "South of Market", "title": "Matisse's Femme au chapeau: A Modern Scandal", "start_date": "2026-05-16", "end_date": "2026-09-13", "url": "https://www.sfmoma.org/exhibition/matisse-femme-au-chapeau/", "summary": "A major exhibition tracing the 1905 debut and enduring influence of Matisse's iconic painting."},
    {"museum": "SFMOMA", "neighborhood": "South of Market", "title": "Graciela Iturbide: Between Two Worlds", "start_date": "2026-07-11", "end_date": "2026-11-29", "url": "https://www.sfmoma.org/exhibitions/", "summary": "An expansive survey of the Mexico City-based photographer's black-and-white work."},
    {"museum": "SFMOMA", "neighborhood": "South of Market", "title": "Jacob Hashimoto: Giant Arc", "start_date": "2026-08-22", "end_date": "2027-08-22", "url": "https://www.sfmoma.org/upcoming-exhibitions/", "summary": "A site-specific installation of more than 75,000 hand-crafted kites in the Roberts Family Gallery."},
    {"museum": "de Young", "neighborhood": "Golden Gate Park", "title": "Treasures of the Pharaohs", "start_date": "2026-08-01", "end_date": "2027-01-31", "url": "https://www.famsf.org/exhibitions", "summary": "More than 130 works spanning 3,000 years of ancient Egyptian art and culture."},
    {"museum": "Legion of Honor", "neighborhood": "Lincoln Park", "title": "The Etruscans: From the Heart of Ancient Italy", "start_date": "2026-05-02", "end_date": "2026-09-20", "url": "https://www.famsf.org/exhibitions", "summary": "A major presentation of Etruscan art, society and craftsmanship."},
    {"museum": "Asian Art Museum", "neighborhood": "Tenderloin", "title": "Ha Chong-Hyun: Retrospective", "start_date": "2026-09-25", "end_date": "2027-01-25", "url": "https://about.asianart.org/press/ha-chong-hyun-retrospective/", "summary": "The first major North American museum survey of the pioneering Korean contemporary artist."},
    {"museum": "Museum of the African Diaspora", "neighborhood": "South of Market", "title": "Dorian Reid: Calling All Cats!", "start_date": "2026-09-30", "end_date": "2026-12-06", "url": "https://www.moadsf.org/exhibitions", "summary": "An upcoming MoAD Emerging Artist exhibition."},
    {"museum": "Yerba Buena Center for the Arts", "neighborhood": "South of Market", "title": "GaHee Park: Behind the Curtain", "start_date": "2026-08-07", "end_date": "2027-01-03", "url": "https://ybca.org/", "summary": "The first U.S. solo museum exhibition by GaHee Park."},
)

EVENT_SEEDS = (
    {"venue": "Davies Symphony Hall", "neighborhood": "Hayes Valley", "category": "Music", "title": "Samara Joy with the SF Symphony", "start_date": "2026-09-08", "end_date": "2026-09-08", "url": "https://www.sfsymphony.org/", "summary": "Grammy-winning vocalist Samara Joy joins the San Francisco Symphony."},
    {"venue": "SFJAZZ Center", "neighborhood": "Hayes Valley", "category": "Music", "title": "Christian McBride with Benny Green & Gregory Hutchinson", "start_date": "2026-09-10", "end_date": "2026-09-11", "url": "https://www.sfjazz.org/tickets/productions/26-27/christian-mcbride-ray-brown-centennial-celebration/", "summary": "Christian McBride honors Ray Brown with an all-star trio."},
    {"venue": "War Memorial Opera House", "neighborhood": "Hayes Valley", "category": "Opera", "title": "Simon Boccanegra", "start_date": "2026-09-12", "end_date": "2026-09-27", "url": "https://www.sfopera.com/whats-on/", "summary": "San Francisco Opera opens its 2026–27 stage season with Verdi's political drama."},
    {"venue": "SFJAZZ Center", "neighborhood": "Hayes Valley", "category": "Music", "title": "Branford Marsalis & Dianne Reeves Celebrate John Coltrane", "start_date": "2026-09-17", "end_date": "2026-09-20", "url": "https://www.sfjazz.org/tickets/productions/26-27/branford-marsalis-and-dianne-reeves-celebrate-john-coltrane/", "summary": "A four-night centennial celebration of John Coltrane with two NEA Jazz Masters."},
    {"venue": "War Memorial Opera House", "neighborhood": "Hayes Valley", "category": "Opera", "title": "Mary, Queen of Scots", "start_date": "2026-09-20", "end_date": "2026-10-04", "url": "https://www.sfopera.com/whats-on/", "summary": "San Francisco Opera presents the story of Mary Stuart's struggle for the Scottish throne."},
    {"venue": "SFJAZZ Center", "neighborhood": "Hayes Valley", "category": "Music", "title": "Jazz at Lincoln Center Orchestra with Wynton Marsalis", "start_date": "2026-09-22", "end_date": "2026-09-22", "url": "https://www.sfjazz.org/tickets/productions/26-27/jazz-at-lincoln-center-orchestra-wynton-marsalis/", "summary": "Wynton Marsalis returns with the Jazz at Lincoln Center Orchestra for a final Bay Area appearance before stepping down."},
    {"venue": "Asian Art Museum", "neighborhood": "Tenderloin", "category": "Culture", "title": "Ha Chong-Hyun: Retrospective Member Opening Night", "start_date": "2026-09-24", "end_date": "2026-09-24", "url": "https://calendar.asianart.org/", "summary": "Opening-night programming for the museum's major Ha Chong-Hyun retrospective."},
    {"venue": "SFJAZZ Center", "neighborhood": "Hayes Valley", "category": "Music", "title": "Marcus Miller: We Want Miles Centennial Celebration", "start_date": "2026-09-24", "end_date": "2026-09-27", "url": "https://www.sfjazz.org/tickets/productions/26-27/marcus-miller-we-want-miles-centennial-celebration/", "summary": "Marcus Miller revisits music from Miles Davis's electric era."},
)


def _date(value: Any) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except Exception:
        match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _text(value: Any, limit: int = 260) -> str:
    cleaned = " ".join(html_lib.unescape(str(value or "")).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip(" ,;:-") + "…"


def _flatten_jsonld(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        out.append(value)
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                out.extend(_flatten_jsonld(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_flatten_jsonld(item))
    return out


def _jsonld_events(page: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, flags=re.I | re.S):
        try:
            payload = json.loads(html_lib.unescape(raw).strip())
        except Exception:
            continue
        for item in _flatten_jsonld(payload):
            types = item.get("@type")
            names = {str(types)} if not isinstance(types, list) else {str(x) for x in types}
            if not any("Event" in name for name in names):
                continue
            if item.get("name") and item.get("startDate"):
                events.append(item)
    return events


def _normalize_live_event(item: dict[str, Any], source: dict[str, str], kind: str) -> dict[str, Any] | None:
    start = _date(item.get("startDate"))
    if not start:
        return None
    end = _date(item.get("endDate")) or start
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    venue = _text(location.get("name") or source["name"], 90)
    url = item.get("url") or source["url"]
    common = {
        "title": _text(item.get("name"), 150),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "url": urljoin(source["url"], str(url)),
        "summary": _text(item.get("description"), 300),
        "neighborhood": source["neighborhood"],
        "live": True,
    }
    if kind == "exhibition":
        return {**common, "museum": source["name"], "address": source.get("address", "")}
    return {**common, "venue": venue, "category": source.get("category", "Culture")}


def _key(item: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", f"{item.get('title','')} {item.get('museum') or item.get('venue') or ''}".lower()).strip()


def _status(item: dict[str, Any], today: date) -> str:
    start = _date(item.get("start_date"))
    end = _date(item.get("end_date"))
    if start and start > today:
        return "Upcoming"
    if not end or end >= today:
        return "On view" if item.get("museum") else "Upcoming"
    return "Ended"


class ArtsClient:
    def __init__(self) -> None:
        self.timeout = 12.0
        self._semaphore = asyncio.Semaphore(5)

    async def _fetch_source(self, source: dict[str, str], kind: str) -> list[dict[str, Any]]:
        headers = {"User-Agent": "sf-neighborhood-bulletin/1.4"}
        try:
            async with self._semaphore:
                async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
                    response = await client.get(source["url"])
                    response.raise_for_status()
            return [x for x in (_normalize_live_event(item, source, kind) for item in _jsonld_events(response.text)) if x]
        except Exception:
            return []

    async def fetch_recent(self, today: date) -> dict[str, Any]:
        museum_live, venue_live = await asyncio.gather(
            asyncio.gather(*(self._fetch_source(source, "exhibition") for source in MUSEUM_SOURCES)),
            asyncio.gather(*(self._fetch_source(source, "event") for source in VENUE_SOURCES)),
        )
        exhibitions = [dict(item, live=False) for item in EXHIBITION_SEEDS]
        events = [dict(item, live=False) for item in EVENT_SEEDS]
        for group in museum_live:
            exhibitions.extend(group)
        for group in venue_live:
            events.extend(group)

        deduped_exhibitions: dict[str, dict[str, Any]] = {}
        for item in exhibitions:
            end = _date(item.get("end_date"))
            if end and end < today:
                continue
            start = _date(item.get("start_date"))
            if start and start > today + timedelta(days=240):
                continue
            item = {**item, "status": _status(item, today)}
            key = _key(item)
            current = deduped_exhibitions.get(key)
            if not current or (item.get("live") and not current.get("live")):
                deduped_exhibitions[key] = item

        deduped_events: dict[str, dict[str, Any]] = {}
        for item in events:
            end = _date(item.get("end_date")) or _date(item.get("start_date"))
            start = _date(item.get("start_date"))
            if not start or (end and end < today) or start > today + timedelta(days=180):
                continue
            item = {**item, "status": "Upcoming"}
            key = _key(item)
            current = deduped_events.get(key)
            if not current or (item.get("live") and not current.get("live")):
                deduped_events[key] = item

        exhibit_list = sorted(deduped_exhibitions.values(), key=lambda x: (x.get("status") == "Upcoming", x.get("start_date", "")))
        event_list = sorted(deduped_events.values(), key=lambda x: x.get("start_date", ""))

        neighborhoods: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for item in exhibit_list:
            neighborhoods.setdefault(item["neighborhood"], {"exhibitions": [], "events": []})["exhibitions"].append(item)
        for item in event_list:
            neighborhoods.setdefault(item["neighborhood"], {"exhibitions": [], "events": []})["events"].append(item)

        museum_names = sorted({x.get("museum") for x in exhibit_list if x.get("museum")})
        venue_names = sorted({x.get("venue") for x in event_list if x.get("venue")})
        return {
            "configured": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Official museum and venue calendars",
            "source_note": "Current and upcoming listings are assembled from official institution pages. Dated fallback entries are retained only while they remain current, so temporary source-page failures do not empty the Arts desk.",
            "exhibitions": exhibit_list,
            "events": event_list,
            "neighborhoods": neighborhoods,
            "museum_count": len(museum_names),
            "venue_count": len(venue_names),
            "exhibition_count": len(exhibit_list),
            "event_count": len(event_list),
            "museums": museum_names,
            "venues": venue_names,
        }
