#!/usr/bin/env python3
"""Exactly-once move drain (RFC D14/D16, SPEC sections 4 and 6).

Files in, files out.  The open-issue list is a JSON file (a GitHub REST subset)
and the result is two files: canonical ledger lines to append, and a JSON
action plan.  There is no network call and no wall-clock read anywhere in this
script -- every ``gh``/API interaction stays in the workflow, driven by the
emitted action plan, so the whole drain is unit-testable offline and
byte-deterministic for identical inputs.

The seven steps (RFC D14):
  1. consider only ``doom: ``-prefixed issues, ascending by issue number;
  2. issue numbers already in the committed ledger are close-only duplicates
     and never re-appended (they do not consume the per-run cap);
  3. take up to the mapping's per-run drain cap;
  4. re-validate every taken title through ``parse_title.py`` at consume time
     (TOCTOU: the title may have been edited since the triggering event) --
     the title travels as a JSON file, never as argv and never through a shell;
  5. apply the ``new game`` cooldown, the section frame cap, and the SPEC 5.5
     sealed-section policy;
  6. emit the accepted ledger lines for the appender to push;
  7. emit every close under ``post_push`` -- closes run strictly after the
     pushes succeed.

Visitor text never leaves this script: only canonical token ids, bounded
counts, sanitized handles, issue numbers, and fixed reject messages are
written.

Every ``post_push`` entry carries a machine-readable ``reason`` code alongside
its ``action`` and its player-visible ``message``, so the workflow can branch on
*why* an issue was closed without re-deriving a normative constant in YAML or,
worse, string-matching player-visible prose.  ``reason`` is additive: it never
replaces ``message`` and the two always agree.

Section state (SPEC 5.8, normative).  The actions JSON carries one further
top-level member, ``"section": {"state": ...}``, a sibling of
``mapping_version`` / ``moves`` / ``post_push``.  It is not a seventh reason
code: a reason code answers *why did this issue close this way* once per drained
issue, while the section state is one fact per **run** that holds just as firmly
when nothing was drained -- which is exactly the case it exists for, since the
``sealed`` and ``section-cap`` codes can only witness a blocked section where
there happened to be a move to reject.  It is emitted unconditionally on every
exit-0 drain, it is reported as of the *end* of the batch (so it describes the
section the next move lands in, and an applied rollover reports ``open``), and
it is run-local -- never written into ``game/state/``, and not a
``mapping_version`` bump.

Sealed mode (SPEC 5.5, normative).  ``--toolchain`` is the comparand: when any
pin in the current section's header (engine / build / wad / mapping) disagrees
with ``game/toolchain.json`` plus the mapping version, the section is sealed and
the only admissible move is ``doom: new game``.  Every other otherwise-valid
move is *close-rejected in band* with the fixed guidance message, never by
failing the run -- the drain processes issues in ascending number order, so
refusing the batch would re-refuse the same low-numbered issue on every
subsequent run, forever, and the game could never be rescued without a human
closing issues by hand.  The ``new game`` cooldown does not apply while sealed
(rule 6): a sealed game cannot advance, so the anti-grief purpose is
inapplicable and a visitor cannot induce a mismatch.

Usage: drain.py --issues FILE --ledger FILE [--mapping PATH] --toolchain PATH
                --out-moves PATH --out-actions PATH
Exit codes: 0 ok / 2 usage / 5 corrupt input content

@see game/SPEC.md sections 4, 5.5, 6 and 10; RFC D14/D16;
    game/scripts/parse_title.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gamelog

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CORRUPT = 5

PARSER_PATH = Path(__file__).resolve().parent / "parse_title.py"

TITLE_PREFIX = "doom: "
HANDLE_FALLBACK = "player"
HANDLE_MAX = 39  # SPEC 5.3 handle grammar
_HANDLE_STRIP_RE = re.compile(r"[^A-Za-z0-9-]")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

ACTION_APPLIED = "close-applied"
ACTION_DUPLICATE = "close-duplicate"
ACTION_REJECT = "close-reject"

#: Machine-readable ``post_push`` reason codes.  Exactly one per entry, always
#: agreeing with ``action`` (the pairing is asserted by the drain tests).  The
#: workflow branches on these -- in particular ``section-cap`` selects the
#: LOG_FULL state screen and ``sealed`` the SEALED one -- so that no normative
#: constant is re-derived in YAML and no player-visible string is ever matched.
REASON_APPLIED = "applied"
REASON_DUPLICATE = "duplicate"
REASON_GRAMMAR = "grammar"
REASON_COOLDOWN = "cooldown"
REASON_SECTION_CAP = "section-cap"
REASON_SEALED = "sealed"

ACTION_FOR_REASON = {
    REASON_APPLIED: ACTION_APPLIED,
    REASON_DUPLICATE: ACTION_DUPLICATE,
    REASON_GRAMMAR: ACTION_REJECT,
    REASON_COOLDOWN: ACTION_REJECT,
    REASON_SECTION_CAP: ACTION_REJECT,
    REASON_SEALED: ACTION_REJECT,
}

#: SPEC section 6, verbatim: the section-cap guidance string is normative.
LOG_FULL_MESSAGE = "log full — start a new game"
#: SPEC 5.5 rule 3, verbatim -- fixed per class, no interpolation, echo-free.
SEALED_MESSAGE = "the arcade is being upgraded — press New game to continue"

RESET_TOKEN = "new-game"


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"drain: {message}\n")
    return code


def sanitize_handle(login) -> str:
    """SPEC 5.3: [a-zA-Z0-9-]{1,39}; strip, truncate, fall back."""
    if not isinstance(login, str):
        return HANDLE_FALLBACK
    cleaned = _HANDLE_STRIP_RE.sub("", login)[:HANDLE_MAX]
    return cleaned or HANDLE_FALLBACK


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def close_entry(issue: int, reason: str, message=None) -> dict:
    """One ``post_push`` entry, with ``action`` derived from ``reason``.

    Deriving rather than passing both is what makes "reason and action never
    disagree" a property of the code instead of a convention.
    """
    return {"issue": issue, "action": ACTION_FOR_REASON[reason],
            "message": message, "reason": reason}


def section_is_sealed(header, engine: str, build: str, wad: str,
                      mapping_version: int) -> bool:
    """SPEC 5.5: any header pin disagreeing with the running toolchain seals."""
    return (
        header.engine != engine
        or header.build != build
        or header.wad != wad
        or header.mapping != mapping_version
    )


def section_state(section_states, sealed: bool, at_cap: bool) -> str:
    """SPEC 5.8: the state of the section the NEXT move will land in.

    ``section_states`` is the mapping's list, normatively in *precedence* order
    -- sealed beats capped beats open -- so the predicates are tested in that
    same order and the first that holds wins.  A section can satisfy both of the
    first two and ``sealed`` must win, which is the order the drain already
    applies when admitting moves, so the reported state and the admission
    decision cannot disagree.

    The three strings are read out of the mapping rather than pasted here: the
    drift guard already pins the mapping against SPEC 5.8, so reading through it
    means drain.py cannot quietly disagree with the file its consumer looks the
    value up in.
    """
    sealed_state, capped_state, open_state = section_states
    if sealed:
        return sealed_state
    if at_cap:
        return capped_state
    return open_state


def reset_token_id(mapping: dict) -> str:
    """The control token that closes a section, read from the mapping."""
    for entry in mapping["tokens"]:
        if entry.get("control") == "reset":
            return entry["id"]
    return RESET_TOKEN


def validate_title(title: str, mapping_path: Path, workdir: Path):
    """Re-validate a title through parse_title.py. Returns (rc, payload)."""
    payload_path = workdir / "title.json"
    payload_path.write_text(json.dumps({"title": title}), encoding="utf-8")
    env = dict(os.environ)
    env.pop("DOOM_TITLE", None)  # the JSON file is the only transport
    proc = subprocess.run(
        [sys.executable, str(PARSER_PATH),
         "--json", str(payload_path), "--mapping", str(mapping_path)],
        capture_output=True,
        env=env,
    )
    try:
        parsed = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        parsed = None
    return proc.returncode, parsed


def eligible_issues(raw_issues):
    """Well-formed, ``doom: ``-prefixed issues, ascending by number, deduped."""
    picked = {}
    for record in raw_issues:
        if not isinstance(record, dict):
            continue
        number = record.get("number")
        title = record.get("title")
        user = record.get("user")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            continue
        if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
            continue
        created_at = parse_timestamp(record.get("created_at"))
        if created_at is None:
            continue
        if not isinstance(user, dict):
            continue
        if number in picked:
            continue
        picked[number] = {
            "number": number,
            "title": title,
            "created_at": created_at,
            "created_at_text": record["created_at"],
            "handle": sanitize_handle(user.get("login")),
        }
    return [picked[number] for number in sorted(picked)]


def atomic_write_bytes(path: Path, data: bytes) -> None:
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".doom-drain-")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--issues", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH))
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--out-moves", dest="out_moves", required=True)
    parser.add_argument("--out-actions", dest="out_actions", required=True)
    args = parser.parse_args(argv)

    issues_path = Path(args.issues)
    ledger_path = Path(args.ledger)
    mapping_path = Path(args.mapping)
    toolchain_path = Path(args.toolchain)
    for label, path in (("issues", issues_path), ("ledger", ledger_path),
                        ("mapping", mapping_path), ("toolchain", toolchain_path)):
        if not path.is_file():
            return _fail(f"{label} file not found", EXIT_USAGE)
    if not PARSER_PATH.is_file():
        return _fail("parse_title.py is missing", EXIT_USAGE)

    try:
        mapping = gamelog.load_mapping(mapping_path)
    except (OSError, ValueError):
        return _fail("mapping file is unreadable", EXIT_USAGE)
    try:
        knobs = mapping["knobs"]
        cap = int(knobs["drain_cap_issues_per_run"])
        cooldown = timedelta(minutes=int(knobs["new_game_cooldown_minutes"]))
        section_cap = int(knobs["section_cap_frames"])
        mapping_version = int(mapping["mapping_version"])
        frames_per_token = gamelog.token_frames(mapping)
    except (KeyError, TypeError, ValueError):
        return _fail("mapping file has no usable knob table", EXIT_USAGE)
    # SPEC 5.8: three states, in precedence order.  Refusing to run without them
    # is deliberate -- the alternative is emitting a state string this script
    # made up, which is the silent drift the mirrored table exists to prevent.
    section_states = mapping.get("section_states")
    if (not isinstance(section_states, list) or len(section_states) != 3
            or not all(isinstance(state, str) and state
                       for state in section_states)):
        return _fail("mapping file has no usable section_states table", EXIT_USAGE)
    reset_id = reset_token_id(mapping)

    # SPEC 5.5: the sealing comparand is the checked-out toolchain file, never a
    # restored artifact -- which is why this step can run before the engine is
    # even fetched.
    try:
        toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
        running_engine = toolchain["engine"]["commit_sha"]
        running_build = toolchain["engine"]["build_sha256"]["value"]
        running_wad = toolchain["wad"]["sha256"]
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError):
        return _fail("toolchain file carries no readable engine/wad pins", EXIT_CORRUPT)

    try:
        raw_issues = json.loads(issues_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return _fail("issues file is not valid JSON", EXIT_CORRUPT)
    if not isinstance(raw_issues, list):
        return _fail("issues file must hold a JSON array", EXIT_CORRUPT)

    try:
        ledger_text = ledger_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return _fail("ledger file is unreadable or not ASCII", EXIT_CORRUPT)
    try:
        log = gamelog.parse_log(ledger_text, mapping)
    except ValueError as exc:
        return _fail(f"corrupt ledger: {exc}", EXIT_CORRUPT)

    ledgered = set()
    last_reset = None
    for section in log.sections:
        for entry in section.entries:
            ledgered.add(entry.issue)
            if entry.token == reset_id:
                last_reset = parse_timestamp(entry.ts)
    section_frames = sum(
        frames_per_token.get(entry.token, 0) * entry.count
        for entry in log.sections[-1].entries
    )
    sealed = section_is_sealed(log.sections[-1].header, running_engine,
                               running_build, running_wad, mapping_version)

    moves = []
    move_lines = []
    post_push = []
    taken = 0

    with tempfile.TemporaryDirectory(prefix="doom-drain-") as workdir_name:
        workdir = Path(workdir_name)
        for issue in eligible_issues(raw_issues):
            number = issue["number"]
            if number in ledgered:
                post_push.append(close_entry(number, REASON_DUPLICATE))
                continue
            if taken >= cap:
                continue  # left open for the next run; no action of any kind
            taken += 1

            code, parsed = validate_title(issue["title"], mapping_path, workdir)
            if code == 1 and isinstance(parsed, dict):
                post_push.append(
                    close_entry(number, REASON_GRAMMAR, parsed.get("message"))
                )
                continue
            if code != 0 or not isinstance(parsed, dict) or parsed.get("ok") is not True:
                return _fail("parse_title.py failed to classify a title", EXIT_USAGE)

            token = parsed["token"]
            count = int(parsed["count"])

            if token == reset_id:
                # SPEC 5.5 rule 6: the cooldown does not apply while sealed --
                # a sealed game cannot advance, so there is nothing to grief,
                # and the sanctioned rollover must stay immediately reachable.
                if (not sealed and last_reset is not None
                        and issue["created_at"] - last_reset < cooldown):
                    post_push.append(close_entry(
                        number,
                        REASON_COOLDOWN,
                        "the game was reset recently — new game is limited to one "
                        f"every {int(knobs['new_game_cooldown_minutes'])} minutes",
                    ))
                    continue
                last_reset = issue["created_at"]
                section_frames = 0
                # The rollover opens a section carrying the running pins, so the
                # rest of this batch applies normally (SPEC 5.5 rule 5).
                sealed = False
            elif sealed:
                # SPEC 5.5 rule 3: reject in band, never fail the run. Refusing
                # the batch would re-refuse this same low-numbered issue on every
                # later run -- the livelock this rule exists to prevent.
                post_push.append(close_entry(number, REASON_SEALED, SEALED_MESSAGE))
                continue
            elif section_frames >= section_cap:
                post_push.append(close_entry(number, REASON_SECTION_CAP,
                                             LOG_FULL_MESSAGE))
                continue
            else:
                section_frames += frames_per_token[token] * count

            entry = gamelog.Entry(
                ts=issue["created_at_text"],
                handle=issue["handle"],
                token=token,
                count=count,
                issue=number,
            )
            try:
                move_lines.append(gamelog.render_ledger_line(entry, mapping))
            except ValueError:
                return _fail("refused to emit a non-canonical ledger line", EXIT_USAGE)
            moves.append({"issue": number, "token": token, "count": count})
            post_push.append(close_entry(number, REASON_APPLIED))

    post_push.sort(key=lambda item: item["issue"])

    # SPEC 5.8 clause 3: as of the END of the batch.  ``sealed`` and
    # ``section_frames`` are the drain loop's own end state, so an applied
    # rollover reports `open` on the very run that healed the game and a batch
    # whose applied moves carry the section over the cap reports `capped`.
    # Reading the pre-loop values instead would describe the section this run
    # *started* with -- it agrees on every quiet fixture and lies on exactly the
    # two runs that change something.
    state = section_state(section_states, sealed, section_frames >= section_cap)

    moves_blob = ("\n".join(move_lines) + "\n").encode("ascii") if move_lines else b""
    actions_blob = (json.dumps(
        {"mapping_version": mapping_version, "moves": moves,
         "post_push": post_push, "section": {"state": state}},
        ensure_ascii=True,
        indent=2,
        sort_keys=False,
    ) + "\n").encode("ascii")

    try:
        atomic_write_bytes(Path(args.out_moves), moves_blob)
        atomic_write_bytes(Path(args.out_actions), actions_blob)
    except OSError:
        return _fail("could not write the output files", EXIT_USAGE)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
