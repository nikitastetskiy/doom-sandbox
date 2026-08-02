#!/usr/bin/env python3
"""Derive the boot-to-gameplay preamble recorded as ``engine.bootstrap_stream``.

SPEC section 1 makes the menu navigation that carries doomreplay from boot into
gameplay "a fixed engine-invocation constant owned by the toolchain": no token
expands to the menu keys ``e``/``x``, so a ledger-derived stream contains only
gameplay keys and never leaves the title screen.  The constant therefore has to
live in ``game/toolchain.json`` -- and it has to be *derived*, not pasted: a
``,,,,,x,,,e...`` blob is unreviewable by inspection.

Source of truth is the committed, empirically verified fixture
``game/tests/fixtures/golden.stream``, whose recorded replay is known to reach
in-level gameplay (``game/tests/fixtures/golden.expected.json``).  The preamble
is the maximal prefix of that fixture's frames that precedes the first gameplay
input -- mechanically: every frame before the first frame holding a key outside
the SPEC section 1 menu set ``{x, e}``.

The frame tokenizer below mirrors ``doomgeneric/i_main.c`` exactly: ``,`` ends a
frame, ``#`` toggles a username tag, every other byte is either a key character
or ignored outright (which is why the fixture's cosmetic line wrapping is
invisible to the engine, and must be invisible here too).

Usage:
  extract_bootstrap.py [--stream PATH]           # print the derived preamble
  extract_bootstrap.py [--stream PATH] --check PATH  # diff it against a toolchain

Exit codes: 0 ok / 2 usage / 4 unusable fixture / 5 recorded value has drifted

@see game/SPEC.md section 1; game/toolchain.json ``engine.bootstrap_stream``;
    game/tests/fixtures/golden.expected.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FIXTURE = 4
EXIT_DRIFT = 5

GAME_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STREAM_PATH = GAME_DIR / "tests" / "fixtures" / "golden.stream"
DEFAULT_TOOLCHAIN_PATH = GAME_DIR / "toolchain.json"

#: Every key character the engine recognises (doomgeneric/i_main.c switch).
#: Any byte outside this set -- newlines included -- is silently ignored.
ENGINE_KEYS = frozenset("xelrudaspftyn<>0123456789")

#: SPEC section 1: the menu/quit keys, unexpandable by construction.  A frame
#: holding only these is menu navigation; anything else is gameplay.
MENU_KEYS = frozenset("xe")

FRAME_SEP = ","
USERNAME_TAG = "#"


def tokenize(text: str) -> list[str]:
    """Split a doomreplay input stream into per-frame key strings.

    Mirrors the engine parser: ``,`` advances the frame, ``#`` opens/closes a
    username tag whose payload is not input, unrecognised bytes are dropped.
    """
    frames: list[str] = [""]
    in_username = False
    for char in text:
        if in_username:
            if char == USERNAME_TAG:
                in_username = False
            continue
        if char == USERNAME_TAG:
            in_username = True
        elif char == FRAME_SEP:
            frames.append("")
        elif char in ENGINE_KEYS:
            frames[-1] += char
    if in_username:
        raise ValueError("unterminated username tag")
    return frames


def extract(text: str) -> str:
    """Return the boot-to-gameplay preamble as a comma-joined frame string.

    The returned value carries NO trailing separator: it is a frame *prefix*,
    and whoever prepends it supplies the comma that closes its last frame (as
    the workflow's ``printf '%s,'`` does).
    """
    frames = tokenize(text)
    boundary = next(
        (i for i, frame in enumerate(frames) if frame and not set(frame) <= MENU_KEYS),
        None,
    )
    if boundary is None:
        raise ValueError("fixture holds no gameplay input; nothing marks the boundary")
    if boundary == 0:
        raise ValueError("fixture opens on gameplay input; it carries no preamble")

    preamble = frames[:boundary]
    pressed = set("".join(preamble))
    if not pressed <= MENU_KEYS:
        raise ValueError(f"preamble holds non-menu keys: {sorted(pressed - MENU_KEYS)}")
    if not {"x", "e"} <= pressed:
        raise ValueError(
            "preamble is not a menu walk: expected both x (escape) and e (enter), "
            f"found {sorted(pressed)}"
        )
    return FRAME_SEP.join(preamble)


def _read(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} is not ASCII: {exc}") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--stream", default=str(DEFAULT_STREAM_PATH),
                        help="fixture the preamble is derived from")
    parser.add_argument("--check", nargs="?", const=str(DEFAULT_TOOLCHAIN_PATH),
                        default=None, metavar="TOOLCHAIN",
                        help="compare engine.bootstrap_stream against the derivation")
    args = parser.parse_args(argv)

    try:
        preamble = extract(_read(Path(args.stream)))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"extract_bootstrap: {exc}\n")
        return EXIT_FIXTURE

    if args.check is None:
        sys.stdout.write(preamble + "\n")
        return EXIT_OK

    try:
        toolchain = json.loads(Path(args.check).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"extract_bootstrap: {exc}\n")
        return EXIT_USAGE

    recorded = toolchain.get("engine", {}).get("bootstrap_stream")
    if recorded == preamble:
        frames = preamble.count(FRAME_SEP) + 1
        sys.stdout.write(f"ok: engine.bootstrap_stream matches the derivation "
                         f"({frames} frames)\n")
        return EXIT_OK

    sys.stderr.write(
        "extract_bootstrap: engine.bootstrap_stream has drifted from "
        f"{args.stream}\n  recorded: {recorded!r}\n  derived:  {preamble!r}\n")
    return EXIT_DRIFT


if __name__ == "__main__":
    sys.exit(main())
