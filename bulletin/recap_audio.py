from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class BulletinBriefAudioClient:
    """Disabled audio client.

    The Bulletin previously generated a neural MP3 during each content refresh.
    Audio generation is intentionally disabled so refreshes cannot make paid TTS
    requests, even when OPENAI_API_KEY or legacy BULLETIN_TTS_* variables remain
    present in the deployment environment.
    """

    def __init__(self) -> None:
        cache_path = Path(os.getenv("CACHE_PATH", "/tmp/bulletin-cache.json"))
        self.audio_path = Path(
            os.getenv("BULLETIN_BRIEF_AUDIO_PATH", str(cache_path.with_name("bulletin-brief.mp3")))
        )
        self.model = None
        self.voice = None
        self.audio_format = None

    @property
    def configured(self) -> bool:
        return False

    @property
    def media_type(self) -> str:
        return "audio/mpeg"

    async def generate(self, snapshot: dict) -> dict[str, Any]:
        # Deliberately make no external API request. Keeping a small metadata object
        # preserves compatibility with app.py while making the disabled state explicit.
        return {
            "transcript": "",
            "word_count": 0,
            "estimated_seconds": 0,
            "snapshot_generated_at": snapshot.get("generated_at"),
            "audio_ready": False,
            "audio_url": None,
            "provider": "Disabled",
            "model": None,
            "voice": None,
            "voice_label": "Audio disabled",
            "ai_narrated": False,
            "audio_format": None,
            "media_type": None,
            "generated_at": None,
            "error": None,
            "disabled": True,
        }
