#!/usr/bin/env python3
"""Anchored, ASCII-only, set-membership parser for DOOM issue titles.

The title is untrusted visitor input.  It arrives ONLY through an environment
variable or a JSON file -- never as an argv value, never through shell string
assembly, never through ``eval``/``exec``.  Matching is a full-string set
membership test against the 56 canonical titles read at runtime from
``game/mapping/v1.json``; there is no unicode normalization, no case folding
and no trimming, so homoglyphs and padded variants fail closed.  Only the
matched canonical token id and its bounded count are ever emitted: the raw
title is never echoed on stdout, on stderr, or into any file.

Usage: parse_title.py [--json FILE] [--mapping PATH]
Exit codes: 0 accept / 1 reject / 2 transport error

@see game/SPEC.md sections 1-4; game/mapping/v1.json; RFC 001 normative
    contracts 1-2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import gamelog

ENV_TITLE = "DOOM_TITLE"

EXIT_ACCEPT = 0
EXIT_REJECT = 1
EXIT_TRANSPORT = 2

#: Fixed per-class rejection messages.  These are visitor-facing and MUST NOT
#: contain any byte of the submitted title (RFC 001 security invariants).
REJECT_MESSAGES = {
    "empty": "empty title — use one of the control links in the README",
    "too-long": "title is too long — use one of the control links in the README",
    "non-ascii": "title contains non-ASCII characters — use one of the control links in the README",
    "bare-prefix": "no command after the prefix — use one of the control links in the README",
    "unlisted-token": "unrecognized command — use one of the control links in the README",
}

BARE_PREFIXES = ("doom:", "doom: ")


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def _reject(reject_class: str) -> int:
    _emit({
        "ok": False,
        "reject_class": reject_class,
        "message": REJECT_MESSAGES[reject_class],
    })
    return EXIT_REJECT


def _transport_error() -> int:
    # Deliberately carries no detail derived from the payload.
    _emit({"ok": False, "error": "transport"})
    return EXIT_TRANSPORT


def title_table(mapping: dict) -> dict:
    """canonical title literal -> (token id, count), derived from the mapping."""
    table = {}
    repeat = mapping["repeat"]
    for entry in mapping["tokens"]:
        table[entry["title"]] = (entry["id"], 1)
        if entry["repeatable"]:
            for count in range(int(repeat["min"]), int(repeat["max"]) + 1):
                table[f"{entry['title']} x{count}"] = (entry["id"], count)
    return table


def _title_bytes(title: str):
    """Encode a title to raw bytes; ``None`` when it is not encodable at all."""
    for errors in ("strict", "surrogateescape"):
        try:
            return title.encode("utf-8", errors)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return None


def classify(raw: bytes, mapping: dict):
    """Return ``(token, count)`` on accept, or a reject-class string."""
    if raw == b"":
        return "empty"
    if len(raw) > int(mapping["knobs"]["title_byte_cap"]):
        return "too-long"
    if any(byte > 0x7F for byte in raw):
        return "non-ascii"
    title = raw.decode("ascii")
    if title in BARE_PREFIXES:
        return "bare-prefix"
    if title not in set(mapping["canonical_titles"]):
        return "unlisted-token"
    resolved = title_table(mapping).get(title)
    if resolved is None:
        # canonical_titles and the token table disagree: a mapping build error.
        return None
    return resolved


def read_title(args) -> tuple:
    """Resolve the title transport. Returns ``(bytes, ok)``."""
    if args.json is not None:
        try:
            payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return b"", False
        if not isinstance(payload, dict):
            return b"", False
        title = payload.get("title")
        if not isinstance(title, str):
            return b"", False
        raw = _title_bytes(title)
        return (raw, True) if raw is not None else (b"", False)
    if ENV_TITLE in os.environ:
        raw = _title_bytes(os.environ[ENV_TITLE])
        return (raw, True) if raw is not None else (b"", False)
    return b"", False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--json", default=None,
                        help="JSON file holding {\"title\": <str>}")
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH),
                        help="path to the versioned command mapping")
    args = parser.parse_args(argv)

    try:
        mapping = gamelog.load_mapping(args.mapping)
    except (OSError, ValueError):
        return _transport_error()

    raw, ok = read_title(args)
    if not ok:
        return _transport_error()

    outcome = classify(raw, mapping)
    if outcome is None:
        return _transport_error()
    if isinstance(outcome, str):
        return _reject(outcome)

    token, count = outcome
    _emit({"ok": True, "token": token, "count": count})
    return EXIT_ACCEPT


if __name__ == "__main__":
    sys.exit(main())
