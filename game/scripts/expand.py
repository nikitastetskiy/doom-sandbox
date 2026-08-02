#!/usr/bin/env python3
"""Token -> doomreplay frame-stream expander (SPEC sections 1, 2, 5).

Every value used here -- token ids, per-frame keys, frame counts, repeat bounds
and the mapping version -- is read at runtime from the mapping file named by
``--mapping``.  Nothing is hardcoded, so a mapping bump is a data change.

The mapping is validated *before* any expansion: every key character must be in
the v1 expansion alphabet and unique within its frame.  Menu/quit keys ``e``
and ``x`` are therefore unexpandable by construction -- there is no allowlist
bypass, a mapping that names them is refused outright.

Usage: expand.py --mapping PATH (--token ID --count N | --ledger FILE)
                 [--expect-mapping-version V]
Exit codes: 0 ok / 2 usage / 3 mapping-version mismatch /
            4 invalid mapping content / 5 invalid ledger input

@see game/SPEC.md sections 1, 2, 5; game/mapping/v1.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gamelog

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VERSION = 3
EXIT_MAPPING = 4
EXIT_LEDGER = 5

#: SPEC 5.4: v1 token expansions draw from this subset of the frame alphabet.
#: ``e``/``x`` are structurally excluded (SPEC section 1 bullet).
V1_EXPANSION_ALPHABET = frozenset("udlrfps")


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"expand: {message}\n")
    return code


def validate_mapping(mapping: dict) -> None:
    """Raise ValueError on any mapping content the expander must refuse."""
    tokens = mapping.get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise ValueError("mapping has no token table")
    if not isinstance(mapping.get("mapping_version"), int):
        raise ValueError("mapping has no integer mapping_version")
    repeat = mapping.get("repeat")
    if not isinstance(repeat, dict) or not isinstance(repeat.get("max"), int):
        raise ValueError("mapping has no repeat bounds")
    seen = set()
    for entry in tokens:
        if not isinstance(entry, dict):
            raise ValueError("mapping token entry is not an object")
        token_id = entry.get("id")
        keys = entry.get("keys")
        frames = entry.get("frames")
        if not isinstance(token_id, str) or not token_id:
            raise ValueError("mapping token entry has no id")
        if token_id in seen:
            raise ValueError("mapping token id is duplicated")
        seen.add(token_id)
        if not isinstance(keys, str):
            raise ValueError("mapping token entry has no keys string")
        if isinstance(frames, bool) or not isinstance(frames, int) or frames < 0:
            raise ValueError("mapping token entry frames must be a non-negative integer")
        for char in keys:
            if char not in V1_EXPANSION_ALPHABET:
                raise ValueError("mapping token entry uses a key outside the v1 alphabet")
        if len(set(keys)) != len(keys):
            raise ValueError("mapping token entry repeats a key within one frame")
        if frames > 0 and not keys:
            raise ValueError("mapping token entry has frames but no keys")


def expand_move(mapping: dict, token: str, count: int):
    keys = gamelog.token_keys(mapping)
    frames_per = gamelog.token_frames(mapping)
    frame = gamelog.canonical_frame(keys[token])
    return [frame] * (frames_per[token] * count)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH))
    parser.add_argument("--token", default=None)
    parser.add_argument("--count", default=None)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--expect-mapping-version", dest="expect_version", default=None)
    args = parser.parse_args(argv)

    move_mode = args.token is not None or args.count is not None
    if move_mode == (args.ledger is not None):
        return _fail("choose exactly one of (--token/--count) or --ledger", EXIT_USAGE)

    mapping_path = Path(args.mapping)
    if not mapping_path.is_file():
        return _fail("mapping file not found", EXIT_USAGE)
    try:
        mapping = gamelog.load_mapping(mapping_path)
    except ValueError:
        return _fail("mapping file is not valid JSON", EXIT_MAPPING)
    except OSError:
        return _fail("mapping file is unreadable", EXIT_USAGE)
    if not isinstance(mapping, dict):
        return _fail("mapping file is not an object", EXIT_MAPPING)

    try:
        validate_mapping(mapping)
    except ValueError as exc:
        return _fail(str(exc), EXIT_MAPPING)

    mapping_version = int(mapping["mapping_version"])
    if args.expect_version is not None:
        try:
            expected = int(args.expect_version)
        except ValueError:
            return _fail("--expect-mapping-version must be an integer", EXIT_USAGE)
        if expected != mapping_version:
            return _fail("mapping version mismatch", EXIT_VERSION)

    if move_mode:
        if args.token is None or args.count is None:
            return _fail("--token and --count are required together", EXIT_USAGE)
        try:
            count = int(args.count)
        except ValueError:
            return _fail("--count must be an integer", EXIT_USAGE)
        if count < 1 or count > int(mapping["repeat"]["max"]):
            return _fail("--count is out of bounds", EXIT_USAGE)
        if args.token not in gamelog.token_ids(mapping):
            return _fail("unknown token id", EXIT_USAGE)
        frames = expand_move(mapping, args.token, count)
    else:
        ledger_path = Path(args.ledger)
        if not ledger_path.is_file():
            return _fail("ledger file not found", EXIT_USAGE)
        try:
            text = ledger_path.read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError):
            return _fail("ledger file is unreadable or not ASCII", EXIT_LEDGER)
        try:
            log = gamelog.parse_log(text, mapping)
        except ValueError as exc:
            return _fail(f"invalid ledger: {exc}", EXIT_LEDGER)
        if len(log.sections) != 1:
            return _fail("ledger input must hold exactly one section", EXIT_LEDGER)
        section = log.sections[0]
        if section.header.mapping != mapping_version:
            return _fail("section header mapping version mismatch", EXIT_VERSION)
        try:
            frames = gamelog.expand_entries(section.entries, mapping)
        except ValueError as exc:
            return _fail(f"invalid ledger: {exc}", EXIT_LEDGER)

    try:
        stream = gamelog.render_stream(frames)
    except ValueError as exc:
        return _fail(f"stream render refused: {exc}", EXIT_MAPPING)
    sys.stdout.buffer.write(stream.encode("ascii"))
    sys.stdout.buffer.flush()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
