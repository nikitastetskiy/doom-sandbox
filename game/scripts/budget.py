#!/usr/bin/env python3
"""GIF encode-budget gate and re-encode ladder (SPEC section 12, RFC D7).

One exact hard ceiling and a forward-only ladder, both read at runtime from the
mapping file: ``budget.ceiling_bytes`` and ``budget.ladder``.  "Exceeds" means
strictly greater than the ceiling -- a GIF of exactly the ceiling size
publishes.  Over the ceiling, the script names the next ladder rung to
re-encode at; over the ceiling at the last rung it hard-fails and nothing is
published.

Usage: budget.py --mapping PATH --rung LEVEL (--size BYTES | --file PATH)
Exit codes: 0 publish / 2 usage / 10 over ceiling, re-encode at "next" /
            11 over ceiling at the last rung: hard fail, no publish

@see game/SPEC.md section 12; RFC D7; game/mapping/v1.json budget
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import gamelog

EXIT_PUBLISH = 0
EXIT_USAGE = 2
EXIT_REENCODE = 10
EXIT_HARD_FAIL = 11


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def _usage(message: str) -> int:
    sys.stderr.write(f"budget: {message}\n")
    return EXIT_USAGE


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH))
    parser.add_argument("--rung", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--size", default=None)
    source.add_argument("--file", default=None)
    args = parser.parse_args(argv)

    mapping_path = Path(args.mapping)
    if not mapping_path.is_file():
        return _usage("mapping file not found")
    try:
        mapping = gamelog.load_mapping(mapping_path)
        budget = mapping["budget"]
        ceiling = int(budget["ceiling_bytes"])
        ladder = list(budget["ladder"])
    except (OSError, ValueError, KeyError, TypeError):
        return _usage("mapping file has no usable budget section")

    levels = [entry["level"] for entry in ladder]
    if args.rung not in levels:
        return _usage("unknown ladder rung")
    index = levels.index(args.rung)

    if args.size is not None:
        try:
            size = int(args.size)
        except ValueError:
            return _usage("--size must be an integer")
        if size < 0:
            return _usage("--size must not be negative")
    else:
        candidate = Path(args.file)
        if not candidate.is_file():
            return _usage("--file does not exist")
        try:
            size = candidate.stat().st_size
        except OSError:
            return _usage("--file is unreadable")

    if size <= ceiling:
        _emit({"publish": True, "rung": args.rung, "size": size,
               "ceiling": ceiling, "hard_fail": False, "next": None})
        return EXIT_PUBLISH

    if index + 1 < len(ladder):
        _emit({"publish": False, "rung": args.rung, "size": size,
               "ceiling": ceiling, "hard_fail": False, "next": ladder[index + 1]})
        return EXIT_REENCODE

    _emit({"publish": False, "rung": args.rung, "size": size,
           "ceiling": ceiling, "hard_fail": True, "next": None})
    return EXIT_HARD_FAIL


if __name__ == "__main__":
    sys.exit(main())
