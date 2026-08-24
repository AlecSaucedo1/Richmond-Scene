from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlparse

import httpx


PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://sf-neighborhood-bulletin.onrender.com").rstrip("/")
INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "8f4f7d5a4d964687aaf4730f4ca67826").strip()
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"


def _xml(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _iso(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _rss_date(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except Exception:
        parsed = datetime.now(timezone.utc)
    return format_datetime(parsed.astimezone(timezone.utc))


def canonical_urls(snapshot: dict | None) -> list[str]:
    urls = [
        f"{PUBLIC_BASE_URL}/",
        f"{PUBLIC_BASE_URL}/near-you",
        f"{PUBLIC_BASE_URL}/city",
        f"{PUBLIC_BASE_URL}/real-estate",
        f"{PUBLIC_BASE_URL}/arts",
        f"{PUBLIC_BASE_URL}/city-hall",
        f"{PUBLIC_BASE_URL}/feed.xml",
    ]
    for item in (snapshot or {}).get("neighborhoods") or []:
        slug = str(item.get("slug") or "").strip()
        if slug:
            urls.append(f"{PUBLIC_BASE_URL}/neighborhood/{slug}")
            urls.append(f"{PUBLIC_BASE_URL}/neighborhood/{slug}/feed.xml")
    return list(dict.fromkeys(urls))


def build_sitemap(snapshot: dict | None) -> str:
    lastmod = _iso((snapshot or {}).get("generated_at"))[:10]
    entries = []
    for url in canonical_urls(snapshot):
        if url.endswith("/feed.xml") or url.endswith("feed.xml"):
            continue
        priority = "1.0" if url == f"{PUBLIC_BASE_URL}/" else ("0.9" if "/neighborhood/" in url else "0.7")
        entries.append(
            f"<url><loc>{_xml(url)}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>daily</changefreq><priority>{priority}</priority></url>"
        )
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + \
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(entries) + "</urlset>"


def _rss_item(title: str, description: str, link: str, guid: str, published: Any, category: str = "") -> str:
    category_xml = f"<category>{_xml(category)}</category>" if category else ""
    return (
        "<item>"
        f"<title>{_xml(title)}</title>"
        f"<description>{_xml(description)}</description>"
        f"<link>{_xml(link)}</link>"
        f"<guid isPermaLink=\"true\">{_xml(guid)}</guid>"
        f"<pubDate>{_xml(_rss_date(published))}</pubDate>"
        f"{category_xml}"
        "</item>"
    )


def build_city_feed(snapshot: dict | None) -> str:
    snapshot = snapshot or {}
    generated = snapshot.get("generated_at")
    items = []
    for story in (snapshot.get("front_page") or [])[:20]:
        slug = story.get("slug") or ""
        source = story.get("source") or ""
        link = f"{PUBLIC_BASE_URL}/neighborhood/{slug}#story-{source}"
        items.append(_rss_item(
            story.get("headline") or "San Francisco neighborhood update",
            story.get("dek") or "Latest neighborhood public-record signal from The San Francisco Bulletin.",
            link,
            link,
            generated,
            story.get("section") or story.get("name") or "San Francisco",
        ))
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\"><channel>"
        "<title>The San Francisco Bulletin</title>"
        f"<link>{_xml(PUBLIC_BASE_URL + '/')}</link>"
        "<description>Neighborhood public-record reporting, local context, development, business, city services, public safety, real estate, arts and dining across San Francisco.</description>"
        "<language>en-us</language>"
        f"<lastBuildDate>{_xml(_rss_date(generated))}</lastBuildDate>"
        + "".join(items) +
        "</channel></rss>"
    )


def build_neighborhood_feed(snapshot: dict | None, slug: str) -> str | None:
    snapshot = snapshot or {}
    edition = (snapshot.get("editions") or {}).get(slug)
    if not edition:
        return None
    generated = snapshot.get("generated_at")
    items = []
    for story in (edition.get("stories") or [])[:12]:
        source = story.get("source") or ""
        link = f"{PUBLIC_BASE_URL}/neighborhood/{slug}#story-{source}"
        items.append(_rss_item(
            story.get("headline") or f"{edition.get('name')} update",
            story.get("dek") or "Latest public-record signal from this neighborhood edition.",
            link,
            link,
            generated,
            story.get("section") or edition.get("name") or "Neighborhood",
        ))
    title = f"{edition.get('name')} Bulletin"
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\"><channel>"
        f"<title>{_xml(title)}</title>"
        f"<link>{_xml(PUBLIC_BASE_URL + '/neighborhood/' + slug)}</link>"
        f"<description>{_xml('Latest public-record and local-context reporting for ' + str(edition.get('name') or 'this San Francisco neighborhood') + '.')}</description>"
        "<language>en-us</language>"
        f"<lastBuildDate>{_xml(_rss_date(generated))}</lastBuildDate>"
        + "".join(items) +
        "</channel></rss>"
    )


def robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        f"Sitemap: {PUBLIC_BASE_URL}/sitemap.xml\n"
    )


async def notify_indexnow(snapshot: dict | None) -> dict[str, Any]:
    if not INDEXNOW_KEY or len(INDEXNOW_KEY) < 8:
        return {"configured": False, "status": "disabled"}
    parsed = urlparse(PUBLIC_BASE_URL)
    urls = [url for url in canonical_urls(snapshot) if not url.endswith("feed.xml")]
    payload = {
        "host": parsed.netloc,
        "key": INDEXNOW_KEY,
        "keyLocation": f"{PUBLIC_BASE_URL}/{INDEXNOW_KEY}.txt",
        "urlList": urls,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.post(INDEXNOW_ENDPOINT, json=payload, headers={"Content-Type": "application/json; charset=utf-8"})
        return {
            "configured": True,
            "status": "accepted" if response.status_code in (200, 202) else "error",
            "http_status": response.status_code,
            "submitted_urls": len(urls),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "configured": True,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "submitted_urls": len(urls),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
