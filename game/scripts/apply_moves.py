#!/usr/bin/env python3
"""Commit drained moves into the ledger and regenerate the stream (SPEC 5.1-5.5).

The state-mutation site of the loop: ``drain.py`` decides *which* moves are
accepted and emits canonical SPEC 5.3 lines; this script is the only thing that
turns those lines into committed game state.  Files in, files out -- no network,
no clock, no shell.

What it does, in order:

  1. **Append** each drained line to the current section, in file order.  A move
     whose issue number already appears anywhere in the ledger is skipped, never
     duplicated (RFC D14 idempotency key) -- which is what makes the workflow's
     fetch/reset/regenerate push-retry loop safe to re-run.
  2. **Roll the section over** on a ``new-game`` directive: the directive is the
     closing section's final line (SPEC 5.3) and the next header is written with
     the *running* pins, which is how an engine/mapping bump legitimately enters
     the log.
  3. **Regenerate** ``--stream`` as ``expand(current section)`` -- the RFC D13
     invariant ``stream == expand(ledger, mapping_version)`` enforced at the
     mutation site rather than only checked in CI.

Sealed sections (SPEC 5.5, normative).  A section is sealed when any header pin
(engine / build / wad / mapping) disagrees with the running toolchain; sealing
is computed here at run time and never stored.  A sealed section never advances
and is never re-simulated: its stream is left byte-untouched and the sole
admissible line is the zero-frame ``new-game`` rollover.  If a frame-contributing
line would land in a sealed section this script **refuses with exit 7 and writes
nothing** (rule 4, defense in depth -- correct drain behaviour rejects those
in-band, so this path should never trigger).

Serialization goes exclusively through ``gamelog``; every blob is rendered and
then re-parsed by the same module before it is allowed near the filesystem, and
both files are written through staged temp files so a failed run leaves the
ledger and the stream byte-identical.

Usage: apply_moves.py --ledger PATH --moves PATH [--mapping PATH]
                      --toolchain PATH --engine-build-sha256 HEX --stream PATH
Exit codes: 0 ok / 2 usage / 5 corrupt content /
            7 determinism pin mismatch (refuse to run, no writes)

Exit 7 is load-bearing: ``.github/workflows/doom.yml`` branches on it to render
the pin-comparison summary instead of reporting a pipeline error.  Never fold it
into 2 or 5.

@see game/SPEC.md sections 1, 5.1-5.5; RFC 001 D13/D14; game/scripts/gamelog.py;
    .github/workflows/doom.yml (frozen call site)
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import gamelog

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CORRUPT = 5
#: SPEC 5.5 rule 4 -- deliberately distinct from 2 and 5; doom.yml branches on it.
EXIT_PIN_MISMATCH = 7

_HEX40_RE = re.compile(r"[0-9a-f]{40}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")

RESET_CONTROL = "reset"
RESET_TOKEN = "new-game"


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"apply_moves: {message}\n")
    return code


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def reset_token_id(mapping: dict) -> str:
    """The control token that closes a section, read from the mapping."""
    for entry in mapping["tokens"]:
        if entry.get("control") == RESET_CONTROL:
            return entry["id"]
    return RESET_TOKEN


def is_sealed(header, engine: str, build: str, wad: str, mapping_version: int) -> bool:
    """SPEC 5.5: any header pin disagreeing with the running toolchain seals."""
    return (
        header.engine != engine
        or header.build != build
        or header.wad != wad
        or header.mapping != mapping_version
    )


def parse_moves(text: str, mapping: dict) -> list:
    """Parse a drain moves file into entries; raise ValueError on anything else.

    Every line must be byte-identical to what ``gamelog`` would render for the
    entry it parses to -- a moves file is canonical SPEC 5.3 or it is refused.
    """
    if text == "":
        return []
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise ValueError("moves file must end with exactly one trailing LF")
    entries = []
    for line in text[:-1].split("\n"):
        entry = gamelog.parse_ledger_line(line, mapping)
        if gamelog.render_ledger_line(entry, mapping) != line:
            raise ValueError("moves line is not canonical")
        entries.append(entry)
    return entries


def stage_write(path: Path, data: bytes):
    """Write ``data`` to a sibling temp file and return it, unrenamed."""
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".doom-apply-")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            try:
                os.chmod(temp_path, path.stat().st_mode & 0o7777)
            except OSError:
                pass
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def commit_writes(writes) -> None:
    """Stage every blob first, then rename them into place.

    Staging is where writes realistically fail (ENOSPC, EACCES, a missing parent
    directory).  Doing all of it before the first rename is what keeps "a failed
    run leaves both files byte-identical" true rather than merely likely.
    """
    staged = []
    try:
        for path, data in writes:
            staged.append((stage_write(path, data), path))
    except BaseException:
        for temp_path, _ in staged:
            temp_path.unlink(missing_ok=True)
        raise
    for temp_path, path in staged:
        os.replace(temp_path, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--moves", required=True)
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH))
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--engine-build-sha256", dest="engine_build_sha256", required=True)
    parser.add_argument("--stream", required=True)
    args = parser.parse_args(argv)

    ledger_path = Path(args.ledger)
    moves_path = Path(args.moves)
    mapping_path = Path(args.mapping)
    toolchain_path = Path(args.toolchain)
    stream_path = Path(args.stream)
    for label, path in (("ledger", ledger_path), ("moves", moves_path),
                        ("mapping", mapping_path), ("toolchain", toolchain_path)):
        if not path.is_file():
            return _fail(f"{label} file not found", EXIT_USAGE)

    running_build = args.engine_build_sha256
    if _HEX64_RE.fullmatch(running_build) is None:
        return _fail("--engine-build-sha256 is not a 64-character lowercase hex digest",
                     EXIT_USAGE)

    # --- Normative values: read at run time, never hardcoded -----------------
    try:
        mapping_text = mapping_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _fail("mapping file is unreadable", EXIT_USAGE)
    try:
        mapping = json.loads(mapping_text)
        mapping_version = int(mapping["mapping_version"])
        frames_per_token = gamelog.token_frames(mapping)
        reset_id = reset_token_id(mapping)
    except (KeyError, TypeError, ValueError):
        return _fail("mapping file has no usable token table", EXIT_CORRUPT)

    try:
        toolchain_text = toolchain_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _fail("toolchain file is unreadable", EXIT_USAGE)
    try:
        toolchain = json.loads(toolchain_text)
        running_engine = toolchain["engine"]["commit_sha"]
        running_wad = toolchain["wad"]["sha256"]
    except (KeyError, TypeError, ValueError):
        return _fail("toolchain file carries no engine/wad pins", EXIT_CORRUPT)
    if not isinstance(running_engine, str) or _HEX40_RE.fullmatch(running_engine) is None:
        return _fail("toolchain engine.commit_sha is not a 40-hex commit SHA", EXIT_CORRUPT)
    if not isinstance(running_wad, str) or _HEX64_RE.fullmatch(running_wad) is None:
        return _fail("toolchain wad.sha256 is not a 64-hex digest", EXIT_CORRUPT)

    # --- Inputs --------------------------------------------------------------
    try:
        ledger_text = ledger_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return _fail("ledger file is unreadable or not ASCII", EXIT_CORRUPT)
    try:
        log = gamelog.parse_log(ledger_text, mapping)
    except ValueError as exc:
        return _fail(f"corrupt ledger: {exc}", EXIT_CORRUPT)

    try:
        moves_text = moves_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return _fail("moves file is unreadable or not ASCII", EXIT_CORRUPT)
    try:
        move_entries = parse_moves(moves_text, mapping)
    except ValueError as exc:
        return _fail(f"corrupt moves file: {exc}", EXIT_CORRUPT)

    # --- Apply (in memory; nothing touches the filesystem until the end) -----
    ledgered = {entry.issue for section in log.sections for entry in section.entries}
    appended = 0
    rollovers = 0
    skipped = 0

    for entry in move_entries:
        if entry.issue in ledgered:
            skipped += 1  # RFC D14: the issue number is the exactly-once key
            continue
        current = log.sections[-1]
        sealed = is_sealed(current.header, running_engine, running_build,
                           running_wad, mapping_version)
        frames = frames_per_token.get(entry.token, 0) * entry.count
        if sealed and frames > 0:
            # SPEC 5.5 rule 4. Refuse rather than advance a sealed section: the
            # committed pins must keep describing the build that produced every
            # frame under them. Nothing has been written at this point.
            return _fail(
                "SPEC 5.5 rule 4: a frame-contributing move would land in a sealed "
                "section (its header pins disagree with the running toolchain); "
                "refusing to run, the ledger and stream are byte-untouched",
                EXIT_PIN_MISMATCH,
            )
        current.entries.append(entry)
        ledgered.add(entry.issue)
        appended += 1
        if entry.token == reset_id:
            # SPEC 5.3: the directive closes this section and the next header
            # follows immediately, carrying the RUNNING pins (SPEC 5.5 rule 2).
            log.sections.append(gamelog.Section(
                header=gamelog.Header(
                    n=current.header.n + 1,
                    engine=running_engine,
                    build=running_build,
                    wad=running_wad,
                    mapping=mapping_version,
                ),
                entries=[],
            ))
            rollovers += 1

    current = log.sections[-1]
    current_sealed = is_sealed(current.header, running_engine, running_build,
                               running_wad, mapping_version)

    # --- Render, then re-parse what was rendered -----------------------------
    try:
        ledger_blob = gamelog.render_log(log, mapping).encode("ascii")
        gamelog.parse_log(ledger_blob.decode("ascii"), mapping)
    except ValueError as exc:
        return _fail(f"refused to emit a non-canonical ledger: {exc}", EXIT_CORRUPT)

    stream_blob = None
    if not current_sealed:
        try:
            frames = gamelog.expand_entries(current.entries, mapping)
            stream_blob = gamelog.render_stream(frames).encode("ascii")
            gamelog.parse_stream(stream_blob.decode("ascii"))
        except ValueError as exc:
            return _fail(f"refused to emit a non-canonical stream: {exc}", EXIT_CORRUPT)

    # --- Write ---------------------------------------------------------------
    writes = []
    if ledger_blob != ledger_text.encode("ascii"):
        writes.append((ledger_path, ledger_blob))
    if stream_blob is not None:
        try:
            existing_stream = stream_path.read_bytes()
        except OSError:
            existing_stream = None
        if existing_stream != stream_blob:
            writes.append((stream_path, stream_blob))
    try:
        commit_writes(writes)
    except OSError:
        return _fail("could not write the ledger or the stream", EXIT_USAGE)

    _emit({
        "ok": True,
        "appended": appended,
        "skipped_duplicates": skipped,
        "rollovers": rollovers,
        "sections": len(log.sections),
        "current_section": current.header.n,
        "sealed": current_sealed,
        "stream_regenerated": stream_blob is not None,
    })
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
