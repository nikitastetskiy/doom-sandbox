#!/usr/bin/env python3
"""Marker-delimited README game-block rewriter (SPEC section 9, must_have 8).

The profile README is a tenant-shared document: this script rewrites ONLY the
bytes strictly between ``<!-- DOOM:START -->`` and ``<!-- DOOM:END -->``.  The
marker pair is validated (present, exactly once, in order) BEFORE anything is
written; on any violation the script exits 6 and leaves the file byte-untouched
-- the fail-safe brick from the RFC's failure-path write contract.

The rendered block is a pure function of (mapping, state, image URL, flags):
applying it twice yields a byte-identical file, and the prior block content is
never consulted.  Control-table labels, titles and the disabled placeholder are
read at runtime from the mapping file, so the rendered links are canonical by
construction (the self-consistency test parses every one of them).

Usage: rewrite_readme.py --readme PATH [--mapping PATH]
                        --state {LIVE,PAUSED,UNAVAILABLE,LOG_FULL}
                        --image-url URL [--controls-enabled]
Exit codes: 0 ok / 2 usage / 6 marker-validation failure

@see game/SPEC.md section 9; game/mapping/v1.json control_links; RFC must_have 8
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path

import gamelog

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MARKER = 6

MARKER_START = b"<!-- DOOM:START -->"
MARKER_END = b"<!-- DOOM:END -->"

STATES = ("LIVE", "PAUSED", "UNAVAILABLE", "LOG_FULL")

#: SPEC section 9: the prefilled new-issue endpoint and body copy.  Neither has
#: a mapping representation -- they are the intake channel itself, not a
#: normative value table.
ISSUE_NEW_URL = "https://github.com/nikitastetskiy/nikitastetskiy/issues/new"
ISSUE_BODY_TEXT = "Just press Submit — your move runs automatically."

CONTROL_TABLE_COLUMNS = 3


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def control_href(title: str) -> str:
    """RFC 3986 %-encoded prefilled-issue URL for one canonical title."""
    return (
        ISSUE_NEW_URL
        + "?title=" + urllib.parse.quote(title, safe="")
        + "&body=" + urllib.parse.quote(ISSUE_BODY_TEXT, safe="")
    )


def control_label(title: str, mapping: dict) -> str:
    """Mapping label for a canonical title, with the repeat suffix appended."""
    labels = {entry["title"]: entry["label"] for entry in mapping["tokens"]}
    if title in labels:
        return labels[title]
    base, sep, suffix = title.rpartition(" x")
    if not sep or base not in labels:
        raise ValueError("control link has no label in the mapping")
    return f"{labels[base]} x{suffix}"


def render_controls(mapping: dict, controls_enabled: bool) -> str:
    if not controls_enabled:
        return mapping["controls_disabled_placeholder"] + "\n"
    titles = list(mapping["control_links"])
    cells = [f"[{control_label(t, mapping)}]({control_href(t)})" for t in titles]
    lines = [
        "|" + " |" * CONTROL_TABLE_COLUMNS,
        "|" + " :---: |" * CONTROL_TABLE_COLUMNS,
    ]
    for start in range(0, len(cells), CONTROL_TABLE_COLUMNS):
        row = cells[start:start + CONTROL_TABLE_COLUMNS]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def render_block(mapping: dict, state: str, image_url: str, controls_enabled: bool) -> bytes:
    """The full marker-block body. Pure function of its arguments."""
    src = html.escape(image_url, quote=True)
    alt = html.escape(f"DOOM ({state})", quote=True)
    block = (
        "\n"
        "<p align=\"center\">\n"
        f"  <img src=\"{src}\" alt=\"{alt}\" />\n"
        "</p>\n"
        "\n"
        + render_controls(mapping, controls_enabled)
        + "\n"
    )
    return block.encode("utf-8")


def validate_markers(data: bytes):
    """Return a marker_error class, or ``None`` when the pair is well formed."""
    starts = data.count(MARKER_START)
    ends = data.count(MARKER_END)
    if starts == 0:
        return "missing-start"
    if ends == 0:
        return "missing-end"
    if starts > 1:
        return "duplicate-start"
    if ends > 1:
        return "duplicate-end"
    if data.index(MARKER_START) > data.index(MARKER_END):
        return "reversed"
    return None


def block_bounds(data: bytes):
    """Byte offsets of the region strictly between the two marker lines."""
    start_marker = data.index(MARKER_START)
    newline = data.find(b"\n", start_marker + len(MARKER_START))
    end_marker = data.index(MARKER_END)
    if newline == -1 or newline > end_marker:
        # The END marker does not begin its own line: no rewritable region.
        return None
    return newline + 1, data.rfind(b"\n", 0, end_marker) + 1


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace ``path`` atomically: write a sibling temp file, then rename."""
    directory = path.parent
    handle, temp_name = tempfile.mkstemp(dir=str(directory), prefix=".doom-readme-")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp_path, path.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--readme", required=True)
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH))
    parser.add_argument("--state", required=True, choices=STATES)
    parser.add_argument("--image-url", dest="image_url", required=True)
    parser.add_argument("--controls-enabled", dest="controls_enabled", action="store_true")
    args = parser.parse_args(argv)

    readme = Path(args.readme)
    if not readme.is_file():
        sys.stderr.write("rewrite_readme: README file not found\n")
        return EXIT_USAGE
    mapping_path = Path(args.mapping)
    if not mapping_path.is_file():
        sys.stderr.write("rewrite_readme: mapping file not found\n")
        return EXIT_USAGE
    try:
        mapping = gamelog.load_mapping(mapping_path)
    except (OSError, ValueError):
        sys.stderr.write("rewrite_readme: mapping file is unreadable\n")
        return EXIT_USAGE

    try:
        data = readme.read_bytes()
    except OSError:
        sys.stderr.write("rewrite_readme: README is unreadable\n")
        return EXIT_USAGE

    bounds = None
    marker_error = validate_markers(data)
    if marker_error is None:
        bounds = block_bounds(data)
        if bounds is None:
            marker_error = "missing-end"
    if marker_error is not None:
        _emit({"ok": False, "marker_error": marker_error})
        return EXIT_MARKER

    start, end = bounds
    try:
        block = render_block(mapping, args.state, args.image_url, args.controls_enabled)
    except (KeyError, ValueError):
        sys.stderr.write("rewrite_readme: mapping is missing control-table values\n")
        return EXIT_USAGE

    rewritten = data[:start] + block + data[end:]
    if rewritten != data:
        atomic_write_bytes(readme, rewritten)
    _emit({"ok": True})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
