from __future__ import annotations

import struct
import zlib
from functools import lru_cache


WIDTH = 1200
HEIGHT = 630
PAPER = (246, 242, 233)
INK = (24, 22, 19)
ACCENT = (143, 32, 35)
DEEP = (228, 221, 207)
MUTED = (112, 105, 92)
SIGNALS = ((143, 32, 35), (24, 22, 19), (138, 106, 47), (72, 91, 103), (94, 75, 60), (108, 79, 115))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _pixel(x: int, y: int) -> tuple[int, int, int]:
    # Editorial paper field and border.
    if x < 28 or x >= WIDTH - 28 or y < 28 or y >= HEIGHT - 28:
        return PAPER
    if x in (42, 43) or y in (42, 43, HEIGHT - 44, HEIGHT - 43):
        return INK

    # Masthead geometry: a restrained red kicker and two heavy ink rules.
    if 70 <= x < 250 and 90 <= y < 116:
        return ACCENT
    if 70 <= x < 1080 and 145 <= y < 208:
        return INK
    if 70 <= x < 820 and 230 <= y < 293:
        return INK
    if 70 <= x < 1080 and 326 <= y < 330:
        return INK

    # Newspaper-column motif.
    if 70 <= y < 520:
        if 70 <= x < 360 and 374 <= y < 388:
            return MUTED
        if 70 <= x < 330 and 402 <= y < 412:
            return DEEP
        if 70 <= x < 340 and 424 <= y < 434:
            return DEEP
        if 430 <= x < 720 and 374 <= y < 388:
            return MUTED
        if 430 <= x < 690 and 402 <= y < 412:
            return DEEP
        if 430 <= x < 705 and 424 <= y < 434:
            return DEEP
        if 790 <= x < 1080 and 374 <= y < 388:
            return MUTED
        if 790 <= x < 1050 and 402 <= y < 412:
            return DEEP
        if 790 <= x < 1065 and 424 <= y < 434:
            return DEEP

    # Live-signal strip echoes the interactive map without depicting invented geography.
    if 70 <= x < 1080 and 480 <= y < 548:
        return DEEP
    if 498 <= y < 530:
        centers = (145, 315, 485, 655, 825, 995)
        for center, color in zip(centers, SIGNALS):
            if (x - center) ** 2 + (y - 514) ** 2 <= 13 ** 2:
                return color

    return PAPER


@lru_cache(maxsize=1)
def build_social_card_png() -> bytes:
    raw = bytearray()
    for y in range(HEIGHT):
        raw.append(0)  # PNG filter type 0
        for x in range(WIDTH):
            raw.extend(_pixel(x, y))
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")
