from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class SnapshotStore:
    def __init__(self, path: str | None = None) -> None:
        configured = path or os.getenv("CACHE_PATH")
        if configured:
            self.path = Path(configured)
        elif os.getenv("RENDER"):
            self.path = Path("/var/data/bulletin-cache.json")
        else:
            self.path = Path(__file__).resolve().parents[1] / "data" / "bulletin-cache.json"

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, snapshot: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=self.path.parent, delete=False, encoding="utf-8") as handle:
            json.dump(snapshot, handle, separators=(",", ":"))
            temp_name = handle.name
        os.replace(temp_name, self.path)
