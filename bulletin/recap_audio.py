from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


TTS_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "marin"
VOICE_INSTRUCTIONS = (
    "Read this as a polished local public-radio news host. Sound natural, warm, calm, "
    "conversational, intelligent, and understated. Use a smooth medium pace around 150 to "
    "160 words per minute, with subtle emphasis on neighborhood names and the key fact in "
    "each story. Use natural sentence-to-sentence transitions and short human pauses. Avoid "
    "an announcer voice, exaggerated enthusiasm, sing-song cadence, robotic spacing, or "
    "dramatic pauses. Read dollar amounts, dates, abbreviations, and San Francisco place names "
    "naturally. Do not add, remove, or paraphrase any words."
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _words(value: str) -> list[str]:
    return [part for part in _clean(value).split(" ") if part]


def _first_sentence(value: Any, max_words: int = 26) -> str:
    clean = _clean(value)
    if not clean:
        return ""
    match = re.match(r"^.*?[.!?](?:\s|$)", clean)
    sentence = match.group(0).strip() if match else clean
    parts = _words(sentence)
    if len(parts) <= max_words:
        return sentence
    return " ".join(parts[:max_words]).rstrip(" ,;:-") + "."


def _headline(value: Any) -> str:
    clean = _clean(value)
    return re.sub(r"\s+-\s+[^-]{2,45}$", "", clean).strip()


def _date_label(value: Any) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return f"{parsed.strftime('%B')} {parsed.day}"
    except Exception:
        return str(value)[:10]


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
        return f"${amount / 1_000:.0f} thousand"
    return f"${amount:,.0f}" if amount else ""


def _stories(snapshot: dict) -> list[dict]:
    picked: list[dict] = []
    used_hoods: set[str] = set()
    used_sources: set[str] = set()
    rows = sorted(snapshot.get("front_page") or [], key=lambda x: float(x.get("interest") or 0), reverse=True)
    for item in rows:
        hood = _clean(item.get("name"))
        source = _clean(item.get("source"))
        if not item.get("headline") or hood in used_hoods:
            continue
        if source in used_sources and len(picked) < 2:
            continue
        picked.append(item)
        if hood:
            used_hoods.add(hood)
        if source:
            used_sources.add(source)
        if len(picked) >= 3:
            break
    return picked


def _dining(snapshot: dict) -> dict | None:
    rows = [
        item for item in (snapshot.get("restaurant_reviews") or [])
        if (item.get("restaurant_verified") or item.get("review_verified"))
        and item.get("verified_neighborhoods")
    ]
    return max(rows, key=lambda x: str(x.get("published") or ""), default=None)


def _arts(snapshot: dict) -> tuple[dict | None, dict | None]:
    arts = snapshot.get("arts") or {}
    exhibits = arts.get("exhibitions") or []
    exhibit = next((item for item in exhibits if item.get("status") == "On view"), None)
    if not exhibit and exhibits:
        exhibit = exhibits[0]
    events = arts.get("events") or []
    return exhibit, events[0] if events else None


def _largest_sale(snapshot: dict) -> dict | None:
    city = ((snapshot.get("real_estate") or {}).get("city") or {})
    for key in ("largest", "largest_residential", "largest_commercial"):
        rows = city.get(key) or []
        if rows:
            return rows[0]
    return None


def build_bulletin_brief(snapshot: dict) -> dict[str, Any]:
    generated_raw = snapshot.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(generated_raw).replace("Z", "+00:00"))
    except Exception:
        generated = datetime.now(timezone.utc)
    day = f"{generated.strftime('%A, %B')} {generated.day}"
    parts = [f"You're listening to the San Francisco Bulletin Brief for {day}. Here's what stands out across the city."]

    for index, item in enumerate(_stories(snapshot)):
        lead = ("First", "Elsewhere", "Also worth watching")[min(index, 2)]
        hood = _clean(item.get("name")) or "San Francisco"
        headline = _headline(item.get("headline"))
        detail = _first_sentence(item.get("dek"), 30 if index == 0 else 24)
        sentence = f"{lead}, in {hood}: {headline}."
        if detail:
            sentence += f" {detail}"
        parts.append(sentence)

    dining = _dining(snapshot)
    if dining:
        hoods = dining.get("verified_neighborhoods") or []
        hood = hoods[0] if hoods else "San Francisco"
        publisher = _clean(dining.get("publisher")) or "local reporting"
        parts.append(f"On the dining desk, {publisher} has recent coverage in {hood}: {_headline(dining.get('title'))}.")

    exhibit, event = _arts(snapshot)
    if exhibit:
        end = f" through {_date_label(exhibit.get('end_date'))}" if exhibit.get("end_date") else ""
        status = _clean(exhibit.get("status")) or "on view"
        parts.append(
            f"In arts, {_headline(exhibit.get('title'))} is {status.lower()} at "
            f"{_clean(exhibit.get('museum'))}{end}."
        )
    if event:
        when = f" on {_date_label(event.get('start_date'))}" if event.get("start_date") else ""
        parts.append(
            f"And on the calendar, {_headline(event.get('title'))} comes to "
            f"{_clean(event.get('venue'))}{when}."
        )

    sale = _largest_sale(snapshot)
    if sale and sale.get("sale_price") and sale.get("address"):
        address = sale.get("address_line") or sale.get("address")
        hood = f" in {sale.get('neighborhood')}" if sale.get("neighborhood") else ""
        parts.append(
            f"In real estate, the largest transaction on the current tape is "
            f"{_money(sale.get('sale_price'))} at {address}{hood}."
        )

    police_through = (((snapshot.get("source_dates") or {}).get("police") or {}).get("latest_report"))
    if police_through:
        parts.append(f"SFPD open-data reports are currently filed through {_date_label(police_through)}.")

    parts.append(
        "That's your Bulletin Brief. Open any neighborhood edition for the records, reporting, "
        "dining, real estate, and arts behind the headlines."
    )

    transcript = re.sub(r"\.\.", ".", " ".join(parts))
    tokens = _words(transcript)
    max_words = 235
    if len(tokens) > max_words:
        transcript = " ".join(tokens[: max_words - 11]).rstrip(" ,;:-")
        transcript += ". That's your Bulletin Brief. Read more across the neighborhood editions."
        tokens = _words(transcript)

    return {
        "transcript": transcript,
        "word_count": len(tokens),
        "estimated_seconds": round(len(tokens) / 155 * 60),
        "snapshot_generated_at": snapshot.get("generated_at"),
    }


class BulletinBriefAudioClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("BULLETIN_TTS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.voice = os.getenv("BULLETIN_TTS_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE
        self.timeout = float(os.getenv("BULLETIN_TTS_TIMEOUT_SECONDS", "45"))
        cache_path = Path(os.getenv("CACHE_PATH", "/tmp/bulletin-cache.json"))
        self.audio_path = Path(os.getenv("BULLETIN_BRIEF_AUDIO_PATH", str(cache_path.with_name("bulletin-brief.mp3"))))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def generate(self, snapshot: dict) -> dict[str, Any]:
        brief = build_bulletin_brief(snapshot)
        meta = {
            **brief,
            "audio_ready": False,
            "audio_url": None,
            "provider": "OpenAI" if self.configured else "Browser fallback",
            "model": self.model if self.configured else None,
            "voice": self.voice if self.configured else None,
            "voice_label": "Marin neural voice" if self.voice == "marin" else f"{self.voice.title()} neural voice",
            "ai_narrated": self.configured,
        }
        if not self.configured:
            meta["error"] = "OPENAI_API_KEY is not configured"
            return meta

        payload = {
            "model": self.model,
            "voice": self.voice,
            "input": brief["transcript"],
            "instructions": VOICE_INSTRUCTIONS,
            "response_format": "mp3",
            "speed": 1.0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "sf-neighborhood-bulletin/1.5",
        }
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.post(TTS_URL, json=payload, headers=headers)
            response.raise_for_status()
            audio = response.content
        if not audio:
            raise RuntimeError("OpenAI speech generation returned an empty audio response")

        self.audio_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.audio_path.with_suffix(".tmp.mp3")
        temp_path.write_bytes(audio)
        os.replace(temp_path, self.audio_path)

        meta.update({
            "audio_ready": True,
            "audio_url": "/api/bulletin-brief/audio",
            "audio_bytes": len(audio),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        })
        return meta
