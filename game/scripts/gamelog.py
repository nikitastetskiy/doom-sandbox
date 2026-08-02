#!/usr/bin/env python3
"""Canonical, byte-exact serialization for the DOOM game log (SPEC section 5).

Importable module -- no side effects at import time, no network, no clock.
Every grammar violation raises ``ValueError``; nothing is ever "repaired".

Normative values (token ids, repeatability, repeat bounds) are read at runtime
from ``game/mapping/v1.json`` -- never hardcoded here.  The only literal
grammar constants in this file are the ones SPEC section 5 defines *as*
grammar (field layout, hex widths, the doomreplay frame alphabet); they have no
representation in the mapping file.

@see game/SPEC.md section 5; game/mapping/v1.json
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# NOTE: deliberately no ``from __future__ import annotations`` here. The test
# harness loads this module via importlib.util.spec_from_file_location without
# registering it in sys.modules; with string annotations, dataclasses' KW_ONLY
# probe (dataclasses._is_type) resolves cls.__module__ through sys.modules and
# raises AttributeError on the None it gets back. Real annotation objects avoid
# that lookup entirely.

# --- Mapping access ---------------------------------------------------------

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent / "mapping" / "v1.json"

_MAPPING_CACHE: dict = {}


def load_mapping(path=None) -> dict:
    """Load and cache a mapping document (defaults to game/mapping/v1.json)."""
    resolved = Path(path) if path is not None else DEFAULT_MAPPING_PATH
    key = str(resolved)
    if key not in _MAPPING_CACHE:
        _MAPPING_CACHE[key] = json.loads(resolved.read_text(encoding="utf-8"))
    return _MAPPING_CACHE[key]


def resolve_mapping(mapping=None) -> dict:
    """Accept an already-loaded mapping dict, a path, or None (default file)."""
    if isinstance(mapping, dict):
        return mapping
    return load_mapping(mapping)


def token_ids(mapping=None) -> tuple:
    return tuple(entry["id"] for entry in resolve_mapping(mapping)["tokens"])


def token_frames(mapping=None) -> dict:
    """token id -> frame count contributed by a single (count=1) move."""
    return {entry["id"]: int(entry["frames"]) for entry in resolve_mapping(mapping)["tokens"]}


def token_keys(mapping=None) -> dict:
    """token id -> the raw keys string for one frame (uncanonicalized)."""
    return {entry["id"]: entry["keys"] for entry in resolve_mapping(mapping)["tokens"]}


def _count_bounds(mapping=None):
    doc = resolve_mapping(mapping)
    repeatable = {entry["id"]: bool(entry["repeatable"]) for entry in doc["tokens"]}
    return repeatable, int(doc["repeat"]["max"])


# --- Grammar constants (SPEC section 5; no mapping representation) ----------

#: SPEC 5.4 frame alphabet -- the doomreplay key set.  ``e``/``x`` are absent
#: by construction (menu/quit keys are never expandable).
STREAM_ALPHABET = frozenset("udlrfps<>0123456789")

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_HEADER_RE = re.compile(
    r"#section (?P<n>[1-9][0-9]*)"
    r" engine=(?P<engine>[0-9a-f]{40})"
    r" build=(?P<build>[0-9a-f]{64})"
    r" wad=(?P<wad>[0-9a-f]{64})"
    r" mapping=(?P<mapping>0|[1-9][0-9]*)"
)

_LEDGER_RE = re.compile(
    r"(?P<ts>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)"
    r" (?P<handle>[A-Za-z0-9-]{1,39})"
    r" (?P<token>[a-z][a-z-]*)"
    r" (?P<count>[0-9])"
    r" #(?P<issue>[1-9][0-9]*)"
)

_HEADER_TAG = "#section "


# --- Value objects -----------------------------------------------------------

@dataclass(frozen=True)
class Header:
    n: int
    engine: str
    build: str
    wad: str
    mapping: int


@dataclass(frozen=True)
class Entry:
    ts: str
    handle: str
    token: str
    count: int
    issue: int


@dataclass
class Section:
    header: Header
    entries: list = field(default_factory=list)


@dataclass
class Log:
    sections: list = field(default_factory=list)


# --- Line-level helpers -------------------------------------------------------

def _require_line(text) -> str:
    if not isinstance(text, str):
        raise ValueError("expected a str line")
    if not text.isascii():
        raise ValueError("non-ASCII byte in line")
    if "\n" in text or "\r" in text or "\t" in text:
        raise ValueError("line contains a newline, carriage return, or tab")
    return text


def parse_header(line, mapping=None) -> Header:
    """Parse one SPEC 5.2 section header line."""
    text = _require_line(line)
    match = _HEADER_RE.fullmatch(text)
    if match is None:
        raise ValueError("malformed section header")
    return Header(
        n=int(match.group("n")),
        engine=match.group("engine"),
        build=match.group("build"),
        wad=match.group("wad"),
        mapping=int(match.group("mapping")),
    )


def render_header(header, mapping=None) -> str:
    """Render a SPEC 5.2 section header line (validated on the way out)."""
    line = (
        f"{_HEADER_TAG}{header.n}"
        f" engine={header.engine}"
        f" build={header.build}"
        f" wad={header.wad}"
        f" mapping={header.mapping}"
    )
    parse_header(line, mapping)
    return line


def parse_ledger_line(line, mapping=None) -> Entry:
    """Parse one SPEC 5.3 ledger line."""
    text = _require_line(line)
    match = _LEDGER_RE.fullmatch(text)
    if match is None:
        raise ValueError("malformed ledger line")

    ts = match.group("ts")
    try:
        datetime.strptime(ts, _TS_FORMAT)
    except ValueError as exc:
        raise ValueError("ledger line carries an impossible timestamp") from exc

    token = match.group("token")
    repeatable, count_max = _count_bounds(mapping)
    if token not in repeatable:
        raise ValueError("ledger line carries an unlisted token id")

    count = int(match.group("count"))
    if count < 1 or count > count_max:
        raise ValueError("ledger line count is out of bounds")
    if not repeatable[token] and count != 1:
        raise ValueError("ledger line repeats a non-repeatable token")

    return Entry(
        ts=ts,
        handle=match.group("handle"),
        token=token,
        count=count,
        issue=int(match.group("issue")),
    )


def render_ledger_line(entry, mapping=None) -> str:
    """Render a SPEC 5.3 ledger line (validated on the way out)."""
    line = f"{entry.ts} {entry.handle} {entry.token} {entry.count} #{entry.issue}"
    parse_ledger_line(line, mapping)
    return line


# --- File-level: the log (SPEC 5.1) ------------------------------------------

def _require_file_text(text) -> str:
    if not isinstance(text, str):
        raise ValueError("expected str file content")
    if not text.isascii():
        raise ValueError("non-ASCII byte in file")
    if "\r" in text:
        raise ValueError("CR byte in file (LF newlines only)")
    if "\t" in text:
        raise ValueError("tab in file (single 0x20 separators only)")
    if not text.endswith("\n"):
        raise ValueError("file must end with exactly one trailing LF")
    if text.endswith("\n\n"):
        raise ValueError("file must end with exactly one trailing LF")
    return text


def parse_log(text, mapping=None) -> Log:
    """Parse a full SPEC 5.1 log file into sections."""
    body = _require_file_text(text)
    log = Log(sections=[])
    expected_n = 1
    for line in body[:-1].split("\n"):
        if line.startswith("#"):
            header = parse_header(line, mapping)
            if header.n != expected_n:
                raise ValueError("section numbers must start at 1 and increase by 1")
            expected_n += 1
            log.sections.append(Section(header=header, entries=[]))
            continue
        if not log.sections:
            raise ValueError("ledger line before any section header")
        log.sections[-1].entries.append(parse_ledger_line(line, mapping))
    if not log.sections:
        raise ValueError("log contains no section")
    return log


def render_log(log, mapping=None) -> str:
    """Render a full SPEC 5.1 log file, byte-exact."""
    lines = []
    expected_n = 1
    for section in log.sections:
        if section.header.n != expected_n:
            raise ValueError("section numbers must start at 1 and increase by 1")
        expected_n += 1
        lines.append(render_header(section.header, mapping))
        for entry in section.entries:
            lines.append(render_ledger_line(entry, mapping))
    if not lines:
        raise ValueError("log contains no section")
    return "\n".join(lines) + "\n"


# --- Frame stream (SPEC 5.4) --------------------------------------------------

def validate_frame(frame) -> str:
    """A frame: zero or more alphabet keys, unique, ascending ASCII order."""
    if not isinstance(frame, str):
        raise ValueError("frame must be a str")
    for char in frame:
        if char not in STREAM_ALPHABET:
            raise ValueError("frame contains a key outside the SPEC 5.4 alphabet")
    if len(set(frame)) != len(frame):
        raise ValueError("frame repeats a key")
    if list(frame) != sorted(frame):
        raise ValueError("frame keys are not in ascending ASCII order")
    return frame


def canonical_frame(keys) -> str:
    """Canonicalize a mapping's keys string into SPEC 5.4 frame order."""
    return validate_frame("".join(sorted(keys)))


def parse_stream(text) -> list:
    """Parse a SPEC 5.4 frame-stream file into its list of frames."""
    if not isinstance(text, str):
        raise ValueError("expected str stream content")
    if not text.isascii():
        raise ValueError("non-ASCII byte in stream")
    if "\r" in text or "\t" in text:
        raise ValueError("stream contains a CR or tab")
    if not text.endswith("\n"):
        raise ValueError("stream must end with exactly one trailing LF")
    body = text[:-1]
    if "\n" in body:
        raise ValueError("stream must contain exactly one LF, at end of file")
    if body == "":
        return []
    frames = body.split(",")
    if frames[-1] == "":
        raise ValueError("stream must not end with a separator")
    for frame in frames:
        validate_frame(frame)
    return frames


def render_stream(frames) -> str:
    """Render frames as a SPEC 5.4 stream file, byte-exact."""
    if isinstance(frames, str) or not isinstance(frames, (list, tuple)):
        raise ValueError("frames must be a list of str")
    items = list(frames)
    if not items:
        return "\n"
    if items[-1] == "":
        raise ValueError(
            "a trailing empty frame is byte-unrepresentable "
            "(collides with the empty-file / no-trailing-separator rules)"
        )
    for frame in items:
        validate_frame(frame)
    return ",".join(items) + "\n"


def expand_entries(entries, mapping=None) -> list:
    """Expand ledger entries into their concatenated SPEC 5.4 frame list."""
    doc = resolve_mapping(mapping)
    keys = token_keys(doc)
    frames_per = token_frames(doc)
    out = []
    for entry in entries:
        if entry.token not in keys:
            raise ValueError("ledger entry carries an unlisted token id")
        frame = canonical_frame(keys[entry.token])
        out.extend([frame] * (frames_per[entry.token] * entry.count))
    return out
