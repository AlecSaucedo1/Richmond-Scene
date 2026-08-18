from __future__ import annotations

import re
from typing import Any

from . import analysis as base


REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\br\s*&\s*r\b", "remove and replace"),
    (r"\br\s*/\s*r\b", "remove and replace"),
    (r"\(e\)", "existing"),
    (r"\(n\)", "new"),
    (r"\bw/o\b", "without"),
    (r"\bw/", "with "),
    (r"\breplc?\b\.?", "replace"),
    (r"\binstl?\b\.?", "install"),
    (r"\bext\b\.?",""exterior"),
    (r"\bint\b\.?",""interior"),
    (r"\bbldg\b\.?",""building"),
    (r"\bkitch\b\.?",""kitchen"),
    (r"\bbthr?m\b\.?",""bathroom"),
    (r"\bflr\b\.?",""floor"),
    (r"\bwdw?s?\b\.?",""window"),
    (r"\bmech\b\.?",""mechanical"),
    (r"\belec\b\.?",""electrical"),
    (r"\bplumb\b\.?",""plumbing"),
    (r"\bstruct\b\.?",""structural"),
    (r"\bgr\b\.?",""ground"),
    (r"\brm\b\.?",""room"),
    (r"\bclg\b\.?",""ceiling"),
    (r"\bdemo\b\.?",""demolish"),
    (r"\btyp\b\.?",""typical"),
    (r"\bT\s*\.?\s*I\b\.?",""tenant improvements"),
    (r"\bMEP\b", "mechanical, electrical and plumbing"),
    (r"\bADA\b", "ADA accessibility"),
    (r"\bADU\b", "accessory dwelling unit (ADU)"),
    (r"\bN/?A\b", ""),
)


def readable_permit_scope(value: Any) -> str:
    raw = " ".join(str(value or "").replace("\n", " ").split()).strip()
    if not raw:
        return "Scope of work was not described in the public filing."

    letters = [char for char in raw if char.isalpha()]
    mostly_upper = bool(letters) and sum(char.isupper() for char in letters) / len(letters) > 0.78

    cleaned = raw
    for pattern, replacement in REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)

    cleaned = cleaned.replace("&", " and ").replace("@", " at ")
    cleaned = re.sub(r"\s*;\s*", ". ", cleaned)
    cleaned = re.sub(r"\s*\|\s*", ". ", cleaned)
    cleaned = re.sub(r"\s+-\s+", " — ", cleaned)

    if mostly_upper:
        cleaned = cleaned.lower()

    # Restore familiar technical abbreviations after sentence-casing an all-caps entry.
    cleaned = re.sub(r"\bada accessibility\b", "ADA accessibility", cleaned, flags=re.I)
    cleaned = re.sub(
        r"\baccessory dwelling unit \(adu\)\b",
        "accessory dwelling unit (ADU)",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\bhvac\b", "HVAC", cleaned, flags=re.I)

    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"([.]){2,}", ".", cleaned)
    cleaned = cleaned.strip(" .,-—")
    if not cleaned:
        return "Scope of work was not described in the public filing."

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [part[:1].upper() + part[1:] if part else part for part in sentences]
    cleaned = " ".join(sentences)
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return base.text(cleaned, 360)
