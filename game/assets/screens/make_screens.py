#!/usr/bin/env python3
"""Generate the v1 README state screens (SPEC section 11) from original artwork.

Deterministic, stdlib-only (``zlib`` + ``struct``): no image library, no font
file, no third-party or id Software asset is read at any point.  Every pixel
originates here -- the typeface below is a hand-authored 5x9 bitmap face and the
motifs are plain rectangles/triangles -- which is what keeps the licensing story
of a public profile page clean (plan step E6, task 1).

Run:  python3 game/assets/screens/make_screens.py
Out:  game/assets/screens/{paused,unavailable,log-full,sealed}.png (320x200, RGB8)

Screen copy is honest per SPEC section 11:
  PAUSED       -- the default "press play" idle state
  UNAVAILABLE  -- "moves are not being processed right now" (the prior frame is
                  still accurate history; it is not wrong)
  LOG FULL     -- section cap reached: "log full - start a new game"
  SEALED       -- the current section's toolchain pins moved (SPEC 5.5), so the
                  section can no longer advance: "the arcade is being upgraded -
                  press New game to continue".  Distinct from UNAVAILABLE (moves
                  ARE being processed) and from LOG FULL (the section is not
                  full).  Screen-legible rendering of the drain's verbatim
                  sealed-reject message.

LOADING is defined by SPEC section 11 but off by default in v1, so it is not
generated here.

@see game/SPEC.md sections 5.5 and 11; RFC 001 component 6
"""

import struct
import zlib
from pathlib import Path

WIDTH, HEIGHT = 320, 200
OUT_DIR = Path(__file__).resolve().parent

# --- Original 5x9 bitmap typeface -------------------------------------------
# Cell is 5 px wide x 9 px tall.  Rows 0-6 are the cap band (baseline = row 6);
# rows 7-8 carry descenders.  Advance is 6 px (one blank column of tracking).

GLYPH_W, GLYPH_H, ADVANCE = 5, 9, 6

_UPPER = {
    "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
    "C": ".###.|#...#|#....|#....|#....|#...#|.###.",
    "D": "####.|#...#|#...#|#...#|#...#|#...#|####.",
    "E": "#####|#....|#....|####.|#....|#....|#####",
    "F": "#####|#....|#....|####.|#....|#....|#....",
    "G": ".###.|#...#|#....|#.###|#...#|#...#|.###.",
    "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    "I": "#####|..#..|..#..|..#..|..#..|..#..|#####",
    "J": "..###|....#|....#|....#|#...#|#...#|.###.",
    "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    "L": "#....|#....|#....|#....|#....|#....|#####",
    "M": "#...#|##.##|#.#.#|#...#|#...#|#...#|#...#",
    "N": "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#",
    "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    "P": "####.|#...#|#...#|####.|#....|#....|#....",
    "Q": ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
    "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    "S": ".####|#....|#....|.###.|....#|....#|####.",
    "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
    "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
    "W": "#...#|#...#|#...#|#...#|#.#.#|##.##|#...#",
    "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
    "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
    "Z": "#####|....#|...#.|..#..|.#...|#....|#####",
    "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
    "1": "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
    "2": ".###.|#...#|....#|...#.|..#..|.#...|#####",
    "3": "#####|...#.|..##.|....#|....#|#...#|.###.",
    "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
    "5": "#####|#....|####.|....#|....#|#...#|.###.",
    "6": "..##.|.#...|#....|####.|#...#|#...#|.###.",
    "7": "#####|....#|...#.|..#..|.#...|.#...|.#...",
    "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
    "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
    " ": ".....|.....|.....|.....|.....|.....|.....",
    "-": ".....|.....|.....|.###.|.....|.....|.....",
    "—": ".....|.....|.....|#####|.....|.....|.....",
    ".": ".....|.....|.....|.....|.....|.##..|.##..",
    "!": "..#..|..#..|..#..|..#..|..#..|.....|..#..",
    "'": "..#..|..#..|.....|.....|.....|.....|.....",
    ":": ".....|..#..|.....|.....|..#..|.....|.....",
}

# Lowercase: full 9-row cells so descenders (g j p q y) can drop below baseline.
_LOWER = {
    "a": ".....|.....|.###.|....#|.####|#...#|.####|.....|.....",
    "b": "#....|#....|####.|#...#|#...#|#...#|####.|.....|.....",
    "c": ".....|.....|.###.|#....|#....|#....|.###.|.....|.....",
    "d": "....#|....#|.####|#...#|#...#|#...#|.####|.....|.....",
    "e": ".....|.....|.###.|#...#|#####|#....|.###.|.....|.....",
    "f": "..##.|.#...|####.|.#...|.#...|.#...|.#...|.....|.....",
    "g": ".....|.....|.####|#...#|#...#|.####|....#|#...#|.###.",
    "h": "#....|#....|####.|#...#|#...#|#...#|#...#|.....|.....",
    "i": "..#..|.....|.##..|..#..|..#..|..#..|.###.|.....|.....",
    "j": "...#.|.....|..##.|...#.|...#.|...#.|...#.|#..#.|.##..",
    "k": "#....|#....|#..#.|#.#..|##...|#.#..|#..#.|.....|.....",
    "l": ".##..|..#..|..#..|..#..|..#..|..#..|.###.|.....|.....",
    "m": ".....|.....|##.#.|#.#.#|#.#.#|#.#.#|#.#.#|.....|.....",
    "n": ".....|.....|####.|#...#|#...#|#...#|#...#|.....|.....",
    "o": ".....|.....|.###.|#...#|#...#|#...#|.###.|.....|.....",
    "p": ".....|.....|####.|#...#|#...#|#...#|####.|#....|#....",
    "q": ".....|.....|.####|#...#|#...#|#...#|.####|....#|....#",
    "r": ".....|.....|#.##.|##...|#....|#....|#....|.....|.....",
    "s": ".....|.....|.####|#....|.###.|....#|####.|.....|.....",
    "t": ".#...|.#...|####.|.#...|.#...|.#..#|..##.|.....|.....",
    "u": ".....|.....|#...#|#...#|#...#|#..##|.##.#|.....|.....",
    "v": ".....|.....|#...#|#...#|#...#|.#.#.|..#..|.....|.....",
    "w": ".....|.....|#...#|#...#|#.#.#|#.#.#|.#.#.|.....|.....",
    "x": ".....|.....|#...#|.#.#.|..#..|.#.#.|#...#|.....|.....",
    "y": ".....|.....|#...#|#...#|#...#|.####|....#|...#.|.##..",
    "z": ".....|.....|#####|...#.|..#..|.#...|#####|.....|.....",
}


def _rows(spec: str) -> list:
    rows = spec.split("|")
    if len(rows) == 7:            # cap-band glyph: pad the descender rows
        rows = rows + [".....", "....."]
    assert len(rows) == GLYPH_H, spec
    assert all(len(r) == GLYPH_W for r in rows), spec
    return rows


FONT = {ch: _rows(spec) for ch, spec in _UPPER.items()}
FONT.update({ch: _rows(spec) for ch, spec in _LOWER.items()})


def text_width(text: str, scale: int) -> int:
    return (len(text) * ADVANCE - 1) * scale if text else 0


# --- Canvas ------------------------------------------------------------------

class Canvas:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.px = [[(0, 0, 0)] * width for _ in range(height)]

    def set(self, x: int, y: int, color) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = color

    def rect(self, x0: int, y0: int, x1: int, y1: int, color) -> None:
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            for x in range(max(0, x0), min(self.w, x1 + 1)):
                self.px[y][x] = color

    def frame(self, x0: int, y0: int, x1: int, y1: int, color, thickness=1) -> None:
        for t in range(thickness):
            self.rect(x0 + t, y0 + t, x1 - t, y0 + t, color)
            self.rect(x0 + t, y1 - t, x1 - t, y1 - t, color)
            self.rect(x0 + t, y0 + t, x0 + t, y1 - t, color)
            self.rect(x1 - t, y0 + t, x1 - t, y1 - t, color)

    def glyph(self, ch: str, x: int, y: int, scale: int, color) -> None:
        rows = FONT.get(ch)
        if rows is None:
            raise KeyError(f"glyph missing from the bitmap face: {ch!r}")
        for ry, row in enumerate(rows):
            for rx, cell in enumerate(row):
                if cell != "#":
                    continue
                self.rect(x + rx * scale, y + ry * scale,
                          x + rx * scale + scale - 1, y + ry * scale + scale - 1, color)

    def text(self, text: str, x: int, y: int, scale: int, color) -> None:
        for i, ch in enumerate(text):
            self.glyph(ch, x + i * ADVANCE * scale, y, scale, color)

    def centered(self, text: str, y: int, scale: int, color) -> None:
        self.text(text, (self.w - text_width(text, scale)) // 2, y, scale, color)

    def to_png(self, path: Path) -> int:
        raw = b"".join(
            b"\x00" + bytes(v for pixel in row for v in pixel) for row in self.px
        )
        payload = b"".join((
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(raw, 9)),
            _chunk(b"IEND", b""),
        ))
        path.write_bytes(payload)
        return len(payload)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


# --- Shared backdrop ---------------------------------------------------------

INK = (198, 190, 180)
DIM = (132, 124, 116)


def backdrop(accent, accent_dim) -> Canvas:
    """Dark vertical gradient + CRT scanlines + a double frame in the accent."""
    canvas = Canvas(WIDTH, HEIGHT)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        base = (int(17 + 13 * t), int(15 + 5 * t), int(16 + 3 * t))
        if y % 2:
            base = tuple(int(c * 0.82) for c in base)
        canvas.rect(0, y, WIDTH - 1, y, base)
    canvas.frame(0, 0, WIDTH - 1, HEIGHT - 1, accent_dim, thickness=3)
    canvas.frame(6, 6, WIDTH - 7, HEIGHT - 7, accent, thickness=1)
    return canvas


def motif_pause(canvas: Canvas, color) -> None:
    """Two chunky bars -- the universal pause mark."""
    canvas.rect(146, 22, 153, 46, color)
    canvas.rect(166, 22, 173, 46, color)


def motif_warning(canvas: Canvas, color) -> None:
    """A hollow triangle with a bang -- caution, not error."""
    for i in range(13):
        y = 22 + 2 * i
        half = i * 2 + 1
        canvas.rect(160 - half, y, 160 - half + 2, y + 1, color)
        canvas.rect(160 + half - 2, y, 160 + half, y + 1, color)
    canvas.rect(134, 44, 186, 47, color)
    canvas.rect(158, 30, 162, 38, color)   # the bang, drawn inside the hollow
    canvas.rect(158, 40, 162, 42, color)


def motif_padlock(canvas: Canvas, color, keyhole) -> None:
    """A closed padlock -- the section is sealed, not broken."""
    canvas.rect(150, 16, 170, 19, color)   # shackle crown
    canvas.rect(150, 16, 153, 31, color)   # shackle legs, sunk into the body
    canvas.rect(167, 16, 170, 31, color)
    canvas.rect(140, 28, 180, 50, color)   # body
    canvas.rect(157, 34, 163, 40, keyhole)  # keyhole, punched out of the body
    canvas.rect(158, 40, 162, 46, keyhole)


def motif_full_meter(canvas: Canvas, color, fill) -> None:
    """A meter pegged at 100% -- the section cap, drawn literally."""
    canvas.frame(110, 26, 210, 44, color, thickness=2)
    for i in range(9):
        x = 114 + i * 11
        canvas.rect(x, 30, x + 7, 40, fill)


# --- The three v1 screens ----------------------------------------------------

def build_paused() -> Canvas:
    accent, accent_dim = (216, 138, 46), (92, 56, 18)
    canvas = backdrop(accent, accent_dim)
    motif_pause(canvas, accent)
    canvas.centered("PAUSED", 62, 4, accent)
    canvas.centered("IDLE - PRESS PLAY", 120, 2, INK)
    canvas.centered("A MOVE WAKES THE GAME", 148, 2, DIM)
    return canvas


def build_unavailable() -> Canvas:
    accent, accent_dim = (214, 176, 62), (94, 74, 22)
    canvas = backdrop(accent, accent_dim)
    motif_warning(canvas, accent)
    canvas.centered("UNAVAILABLE", 62, 4, accent)
    canvas.centered("MOVES ARE NOT BEING", 116, 2, INK)
    canvas.centered("PROCESSED RIGHT NOW", 140, 2, INK)
    canvas.centered("LAST FRAME STILL VALID", 166, 2, DIM)
    return canvas


def build_log_full() -> Canvas:
    accent, accent_dim = (198, 62, 40), (88, 26, 18)
    canvas = backdrop(accent, accent_dim)
    motif_full_meter(canvas, accent, (150, 44, 30))
    canvas.centered("LOG FULL", 62, 4, accent)
    canvas.centered("start a new game", 118, 2, INK)
    canvas.centered("only NEW GAME accepted", 148, 2, DIM)
    return canvas


def build_sealed() -> Canvas:
    accent, accent_dim = (92, 176, 214), (28, 62, 86)
    canvas = backdrop(accent, accent_dim)
    motif_padlock(canvas, accent, (14, 26, 36))
    canvas.centered("SEALED", 62, 4, accent)
    canvas.centered("the arcade is being", 112, 2, INK)
    canvas.centered("upgraded — press", 136, 2, INK)
    canvas.centered("NEW GAME to continue", 164, 2, DIM)
    return canvas


SCREENS = {
    "paused.png": build_paused,
    "unavailable.png": build_unavailable,
    "log-full.png": build_log_full,
    "sealed.png": build_sealed,
}

MAX_BYTES = 500_000


def main() -> int:
    for name, build in SCREENS.items():
        path = OUT_DIR / name
        size = build().to_png(path)
        # Never trust a successful write: assert the artifact, not the exit code.
        assert size == path.stat().st_size, name
        assert size < MAX_BYTES, f"{name} is {size} bytes (cap {MAX_BYTES})"
        print(f"{name}: {size} bytes, {WIDTH}x{HEIGHT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
