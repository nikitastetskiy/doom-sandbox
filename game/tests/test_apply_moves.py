"""
@spec-handoff
@interface apply_moves.py --ledger PATH --moves PATH --mapping PATH
    --toolchain PATH --engine-build-sha256 HEX --stream PATH
    (argv frozen by .github/workflows/doom.yml, commit 1acb539 — do not change)
    Exit codes: 0 success / 2 usage (bad or missing arguments, unreadable input
    file) / 5 corrupt content (unparseable ledger, moves, mapping or toolchain)
    / 7 DETERMINISM PIN MISMATCH — refuse to run, no writes. doom.yml branches
    on 7, so it is load-bearing: do not fold it into 2 or 5.
@behavior
    - --ledger and --stream are read AND written in place. Every write is
      atomic (temp file + os.replace) and BOTH files are left byte-identical on
      every non-zero exit — a failed run never leaves half-applied state
    - Serialization goes exclusively through gamelog.py (parse_log/render_log/
      parse_ledger_line/render_ledger_line/expand_entries/render_stream); do
      NOT re-implement any grammar. Format-then-re-parse must hold end to end:
      parse_log(render_log(parse_log(x))) == parse_log(x)
    - APPEND: each line of --moves (canonical SPEC 5.3 lines as emitted by
      drain.py) is appended to the current section, in file order. A move whose
      issue number already appears ANYWHERE in the ledger is skipped, not
      duplicated — the idempotency key (RFC D14). This is what makes doom.yml's
      fetch/reset/regenerate push-retry loop safe to run repeatedly
    - ROLLOVER: a `new-game` line is a ledger control directive (SPEC §1). It
      is appended to the CLOSING section and is immediately followed by the
      next section's header (SPEC §5.3 worked example). The new header carries
      n+1 and the RUNNING pins — engine commit SHA and WAD SHA-256 from
      --toolchain, build from --engine-build-sha256, mapping from the mapping
      file's mapping_version — which is how an engine bump legitimately enters
      the log (RFC: an engine bump forces `new game`). Prior sections are
      retained verbatim, never rewritten or truncated
    - CURRENT SECTION = the LAST section in the ledger, which after a rollover
      is the newly opened (entry-less) one
    - STREAM: --stream is rewritten to expand(current section) on every
      successful run, satisfying the RFC-normative
      `stream == expand(ledger, mapping_version)` CI invariant. An entry-less
      current section yields exactly b"\\n" (zero frames, no commas, one LF)
    - SEALED SECTIONS (SPEC §5.5, normative — ratified in 5e2c68f). A section
      is SEALED when any header field (engine/build/wad/mapping) disagrees with
      the running toolchain (--toolchain plus --engine-build-sha256, and the
      mapping file's mapping_version). Sealing is computed at run time and is
      never stored. Then:
      * rule 1 — a sealed section never advances and is never re-simulated: no
        frame-contributing line may be appended to it, and --stream is NOT
        regenerated while sealed (leave the file byte-untouched, even if the
        current contents look stale). Its committed pins stay verbatim so it
        remains reproducible against the archived build that produced it
      * rule 2 — the sole admissible line is a `new-game` directive. It
        contributes zero frames, so it cannot alter the sealed section's replay
        output. It is appended as that section's final line and the next header
        is written with the RUNNING pins: the only legitimate way a pin change
        enters the log
      * rule 4 — DEFENSE IN DEPTH: if any frame-contributing line would land in
        a sealed section, exit 7 with the ledger and stream byte-unchanged.
        Correct drain behaviour sealed-rejects those in-band (drain rule 3), so
        this path should never trigger; implement it anyway
      * rule 5 — once the reset opens a fresh section its pins match by
        construction, so later lines in the same batch land there and are
        simulated normally
@edge-cases
    - Empty --moves file on an UNSEALED section: no-op append, stream still
      regenerated, exit 0 (idempotent re-render)
    - Rollover recovery render: the fresh section is empty, so the recovery run
      replays zero frames and --stream becomes exactly b"\\n"; the sealed
      section's frames are never re-expanded
    - A moves line that is not canonical per gamelog ⇒ exit 5, no writes
@see game/SPEC.md §1, §5.1-5.5 (§5.5 is the normative sealed-section ruling);
    RFC 001 determinism guarantees + D13/D14;
    .github/workflows/doom.yml (frozen call site); game/scripts/gamelog.py
"""

import json

import pytest

from conftest import (
    BUILD_HEX,
    ENGINE_HEX,
    MAPPING_PATH,
    WAD_HEX,
    expected_stream_text,
    make_toolchain,
    import_gamelog,
    ledger_line,
    make_section_text,
    run_script,
    section_header,
)

TS = "2026-08-02T14:02:11Z"


def run_apply(tmp_path, ledger_text, moves_text, *, engine=ENGINE_HEX, wad=WAD_HEX,
              build=BUILD_HEX, build_arg=None, mapping=MAPPING_PATH, toolchain=None,
              stream_text="\n"):
    tmp_path.mkdir(parents=True, exist_ok=True)  # callers may pass a subdirectory
    ledger = tmp_path / "log.txt"
    ledger.write_text(ledger_text, encoding="ascii")
    moves = tmp_path / "moves.txt"
    moves.write_text(moves_text, encoding="ascii")
    stream = tmp_path / "stream.txt"
    stream.write_text(stream_text, encoding="ascii")
    if toolchain is None:
        toolchain = make_toolchain(tmp_path, engine=engine, wad=wad, build=build)
    proc = run_script("apply_moves.py", [
        "--ledger", str(ledger), "--moves", str(moves), "--mapping", str(mapping),
        "--toolchain", str(toolchain),
        "--engine-build-sha256", build_arg if build_arg is not None else build,
        "--stream", str(stream),
    ])
    return proc, ledger, stream


def one_section(entries=(), n=1):
    return make_section_text(list(entries), n=n)


# --- Append -------------------------------------------------------------------

def test_moves_are_appended_to_the_current_section_in_file_order(tmp_path):
    moves = (
        ledger_line(TS, "alice", "fire", 1, 11) + "\n"
        + ledger_line("2026-08-02T14:03:00Z", "bob", "turn-left", 2, 12) + "\n"
    )
    proc, ledger, _ = run_apply(tmp_path, one_section(), moves)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == one_section([
        ledger_line(TS, "alice", "fire", 1, 11),
        ledger_line("2026-08-02T14:03:00Z", "bob", "turn-left", 2, 12),
    ])


def test_append_preserves_prior_entries_verbatim(tmp_path):
    existing = ledger_line("2026-08-02T10:00:00Z", "carol", "forward", 5, 3)
    before = one_section([existing])
    proc, ledger, _ = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "use", 1, 11) + "\n"
    )
    assert proc.returncode == 0
    after = ledger.read_text(encoding="ascii")
    assert after.startswith(before[:-1])  # everything prior is byte-identical
    assert existing in after


def test_empty_moves_file_is_a_successful_no_op_that_still_regenerates_stream(tmp_path):
    before = one_section([ledger_line(TS, "alice", "fire", 1, 11)])
    proc, ledger, stream = run_apply(tmp_path, before, "", stream_text="stale\n")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == before
    assert stream.read_text(encoding="ascii") == expected_stream_text([("fire", 1)])


def test_result_is_byte_identical_to_a_gamelog_round_trip(tmp_path):
    """Serialization must go through gamelog: format-then-re-parse holds."""
    gamelog = import_gamelog()
    proc, ledger, _ = run_apply(
        tmp_path, one_section(), ledger_line(TS, "alice", "fire", 1, 11) + "\n"
    )
    assert proc.returncode == 0
    text = ledger.read_text(encoding="ascii")
    assert gamelog.render_log(gamelog.parse_log(text)) == text


# --- Idempotency (RFC D14) ------------------------------------------------------

def test_move_whose_issue_is_already_ledgered_is_not_appended_twice(tmp_path):
    line = ledger_line(TS, "alice", "fire", 1, 11)
    before = one_section([line])
    proc, ledger, _ = run_apply(tmp_path, before, line + "\n")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == before
    assert ledger.read_text(encoding="ascii").count("#11") == 1


def test_applying_the_same_batch_twice_is_a_fixed_point(tmp_path):
    """doom.yml's push-retry loop re-runs apply_moves after fetch/reset."""
    moves = (
        ledger_line(TS, "alice", "fire", 1, 11) + "\n"
        + ledger_line("2026-08-02T14:03:00Z", "bob", "back", 3, 12) + "\n"
    )
    proc, ledger, stream = run_apply(tmp_path, one_section(), moves)
    assert proc.returncode == 0
    once, once_stream = ledger.read_text(encoding="ascii"), stream.read_text(encoding="ascii")
    proc2, ledger2, stream2 = run_apply(tmp_path / "second", once, moves)
    assert proc2.returncode == 0
    assert ledger2.read_text(encoding="ascii") == once
    assert stream2.read_text(encoding="ascii") == once_stream


def test_partially_ledgered_batch_appends_only_the_new_moves(tmp_path):
    already = ledger_line(TS, "alice", "fire", 1, 11)
    fresh = ledger_line("2026-08-02T14:05:00Z", "bob", "use", 1, 12)
    proc, ledger, _ = run_apply(
        tmp_path, one_section([already]), already + "\n" + fresh + "\n"
    )
    assert proc.returncode == 0
    assert ledger.read_text(encoding="ascii") == one_section([already, fresh])


def test_issue_ledgered_in_a_prior_section_is_still_skipped(tmp_path):
    old = ledger_line("2026-08-02T09:00:00Z", "alice", "fire", 1, 11)
    reset = ledger_line("2026-08-02T09:30:00Z", "alice", "new-game", 1, 12)
    before = make_section_text([old, reset], n=1) + make_section_text([], n=2)
    proc, ledger, _ = run_apply(tmp_path, before, old + "\n")
    assert proc.returncode == 0
    assert ledger.read_text(encoding="ascii") == before


# --- Section rollover -------------------------------------------------------------

def test_new_game_closes_the_section_and_opens_the_next_with_running_pins(tmp_path):
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    proc, ledger, _ = run_apply(tmp_path, one_section(), reset + "\n")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == (
        make_section_text([reset], n=1) + make_section_text([], n=2)
    )


def test_rollover_header_carries_the_running_toolchain_pins_not_the_old_ones(tmp_path):
    """RFC: an engine bump forces `new game`; the NEW header records the new
    pins, which is how a pin change legitimately enters the log."""
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    before = make_section_text([], n=1)  # section 1 carries the default pins
    proc, ledger, _ = run_apply(tmp_path, before, reset + "\n")
    assert proc.returncode == 0
    gamelog = import_gamelog()
    log = gamelog.parse_log(ledger.read_text(encoding="ascii"))
    assert len(log.sections) == 2
    new_header = log.sections[1].header
    assert new_header.n == 2
    assert (new_header.engine, new_header.build, new_header.wad) == (
        ENGINE_HEX, BUILD_HEX, WAD_HEX
    )
    assert new_header.mapping == 1


def test_section_numbers_increase_by_exactly_one(tmp_path):
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    before = make_section_text([], n=1) + make_section_text([], n=2)
    proc, ledger, _ = run_apply(tmp_path, before, reset + "\n")
    assert proc.returncode == 0
    gamelog = import_gamelog()
    log = gamelog.parse_log(ledger.read_text(encoding="ascii"))
    assert [s.header.n for s in log.sections] == [1, 2, 3]


def test_prior_sections_are_retained_verbatim_across_a_rollover(tmp_path):
    old_move = ledger_line("2026-08-02T09:00:00Z", "carol", "forward", 2, 5)
    old_reset = ledger_line("2026-08-02T09:30:00Z", "carol", "new-game", 1, 6)
    before = make_section_text([old_move, old_reset], n=1) + make_section_text([], n=2)
    proc, ledger, _ = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "new-game", 1, 20) + "\n"
    )
    assert proc.returncode == 0
    after = ledger.read_text(encoding="ascii")
    assert after.startswith(make_section_text([old_move, old_reset], n=1))


def test_moves_after_a_rollover_land_in_the_new_section(tmp_path):
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    later = ledger_line("2026-08-02T14:10:00Z", "bob", "fire", 1, 21)
    proc, ledger, stream = run_apply(tmp_path, one_section(), reset + "\n" + later + "\n")
    assert proc.returncode == 0
    assert ledger.read_text(encoding="ascii") == (
        make_section_text([reset], n=1) + make_section_text([later], n=2)
    )
    assert stream.read_text(encoding="ascii") == expected_stream_text([("fire", 1)])


def test_move_before_a_rollover_lands_in_the_closing_section(tmp_path):
    early = ledger_line(TS, "alice", "fire", 1, 19)
    reset = ledger_line("2026-08-02T14:05:00Z", "bob", "new-game", 1, 20)
    proc, ledger, stream = run_apply(tmp_path, one_section(), early + "\n" + reset + "\n")
    assert proc.returncode == 0
    assert ledger.read_text(encoding="ascii") == (
        make_section_text([early, reset], n=1) + make_section_text([], n=2)
    )
    assert stream.read_bytes() == b"\n", "the new current section is entry-less"


def test_two_resets_in_one_batch_open_two_sections(tmp_path):
    r1 = ledger_line(TS, "alice", "new-game", 1, 20)
    r2 = ledger_line("2026-08-02T14:40:00Z", "bob", "new-game", 1, 21)
    proc, ledger, _ = run_apply(tmp_path, one_section(), r1 + "\n" + r2 + "\n")
    assert proc.returncode == 0
    assert ledger.read_text(encoding="ascii") == (
        make_section_text([r1], n=1) + make_section_text([r2], n=2)
        + make_section_text([], n=3)
    )


# --- Current-section extraction + stream regeneration -----------------------------

def test_stream_equals_expand_of_the_current_section_only(tmp_path):
    old = ledger_line("2026-08-02T09:00:00Z", "carol", "forward", 5, 5)
    reset = ledger_line("2026-08-02T09:30:00Z", "carol", "new-game", 1, 6)
    before = make_section_text([old, reset], n=1) + make_section_text([], n=2)
    proc, _, stream = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "fire", 1, 11) + "\n"
    )
    assert proc.returncode == 0
    assert stream.read_text(encoding="ascii") == expected_stream_text([("fire", 1)])
    assert "u" not in stream.read_text(encoding="ascii"), "prior section must not leak"


def test_entry_less_current_section_yields_exactly_one_lf(tmp_path):
    proc, _, stream = run_apply(tmp_path, one_section(), "", stream_text="stale,stale\n")
    assert proc.returncode == 0
    assert stream.read_bytes() == b"\n"


def test_stream_matches_expand_entries_of_the_parsed_current_section(tmp_path):
    gamelog = import_gamelog()
    moves = (
        ledger_line(TS, "alice", "run-forward", 2, 11) + "\n"
        + ledger_line("2026-08-02T14:06:00Z", "bob", "turn-right", 3, 12) + "\n"
    )
    proc, ledger, stream = run_apply(tmp_path, one_section(), moves)
    assert proc.returncode == 0
    log = gamelog.parse_log(ledger.read_text(encoding="ascii"))
    expected = gamelog.render_stream(gamelog.expand_entries(log.sections[-1].entries))
    assert stream.read_text(encoding="ascii") == expected


def test_stale_stream_is_overwritten_not_appended(tmp_path):
    proc, _, stream = run_apply(
        tmp_path, one_section(), ledger_line(TS, "alice", "fire", 1, 11) + "\n",
        stream_text="l,l,l\n",
    )
    assert proc.returncode == 0
    assert stream.read_text(encoding="ascii") == expected_stream_text([("fire", 1)])


# --- Pin guard: refuse to run rather than fork the timeline -------------------------

PIN_MISMATCHES = [
    ("engine-commit-sha", {"engine": "99" * 20}),
    ("engine-build-sha256", {"build_arg": "88" * 32}),
    ("wad-sha256", {"wad": "77" * 32}),
]


@pytest.mark.parametrize(
    ("kwargs",), [(k,) for _, k in PIN_MISMATCHES], ids=[i for i, _ in PIN_MISMATCHES]
)
def test_pin_mismatch_refuses_with_exit_7(tmp_path, kwargs):
    before = one_section([ledger_line("2026-08-02T09:00:00Z", "carol", "fire", 1, 5)])
    proc, ledger, stream = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "forward", 1, 11) + "\n",
        stream_text="f,f\n", **kwargs
    )
    assert proc.returncode == 7, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == before, "refusal must not append"
    assert stream.read_text(encoding="ascii") == "f,f\n", "refusal must not rewrite the stream"


def test_mapping_version_mismatch_in_the_header_refuses_with_exit_7(tmp_path):
    before = make_section_text([], n=1, mapping=2)
    proc, ledger, stream = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "fire", 1, 11) + "\n", stream_text="\n"
    )
    assert proc.returncode == 7
    assert ledger.read_text(encoding="ascii") == before


def test_pin_guard_reads_the_current_section_not_the_first(tmp_path):
    """Only the section being appended to must match the running toolchain;
    archived sections legitimately carry the pins they were played under."""
    stale = section_header(n=1, engine="99" * 20, build="88" * 32, wad="77" * 32)
    reset = ledger_line("2026-08-02T09:30:00Z", "carol", "new-game", 1, 6)
    before = stale + "\n" + reset + "\n" + make_section_text([], n=2)
    proc, ledger, _ = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "fire", 1, 11) + "\n"
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii").startswith(stale)


def test_matching_pins_are_accepted(tmp_path):
    proc, _, _ = run_apply(
        tmp_path, one_section(), ledger_line(TS, "alice", "fire", 1, 11) + "\n"
    )
    assert proc.returncode == 0


def test_zero_frame_reset_is_the_sanctioned_rollover_under_mismatched_pins(tmp_path):
    """SPEC GAP (flagged): a `new-game` line contributes zero frames, so it
    cannot alter the stale section's replay output and cannot fork the
    timeline. Permitting exactly this — and nothing else — is what keeps the
    RFC's "engine bump ⇒ forced new game" reachable in-band."""
    bumped_engine = "99" * 20  # the newly built engine the runner is carrying
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    proc, ledger, _ = run_apply(
        tmp_path, one_section(), reset + "\n", engine=bumped_engine
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    gamelog = import_gamelog()
    log = gamelog.parse_log(ledger.read_text(encoding="ascii"))
    assert len(log.sections) == 2
    assert log.sections[0].header.engine == ENGINE_HEX, (
        "the stale section keeps the pins it was played under, verbatim"
    )
    assert log.sections[1].header.engine == bumped_engine, (
        "the new section records the bumped engine — this is how a pin change "
        "legitimately enters the log"
    )


def test_frame_contributing_move_before_a_reset_is_still_refused(tmp_path):
    """DEFENSE IN DEPTH (SPEC 5.5 rule 4), not the primary policy path.

    Correct drain behaviour sealed-rejects a frame-contributing move in-band
    (SPEC 5.5 rule 3), so apply_moves should never receive such a batch. If it
    does — a drain bug, a hand-made moves file, an operator dispatch — it
    refuses with exit 7 and leaves the ledger byte-unchanged rather than
    advancing a sealed section.
    """
    early = ledger_line(TS, "alice", "fire", 1, 19)
    reset = ledger_line("2026-08-02T14:05:00Z", "bob", "new-game", 1, 20)
    before = one_section()
    proc, ledger, _ = run_apply(
        tmp_path, before, early + "\n" + reset + "\n", engine="99" * 20
    )
    assert proc.returncode == 7, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == before


def test_sealed_section_stream_is_not_regenerated(tmp_path):
    """SPEC 5.5 rule 1: a sealed section is never re-simulated and its
    stream.txt is not regenerated — not even to a 'correct' value."""
    before = one_section([ledger_line("2026-08-02T09:00:00Z", "carol", "fire", 1, 5)])
    proc, ledger, stream = run_apply(
        tmp_path, before, ledger_line(TS, "alice", "forward", 1, 11) + "\n",
        engine="99" * 20, stream_text="deliberately-stale\n",
    )
    assert proc.returncode == 7
    assert stream.read_text(encoding="ascii") == "deliberately-stale\n"
    assert ledger.read_text(encoding="ascii") == before


def test_sanctioned_rollover_renders_the_fresh_empty_section(tmp_path):
    """SPEC 5.5 'rollover recovery render': the fresh section is empty, so the
    recovery run replays zero frames — the sealed section is never re-expanded."""
    sealed_move = ledger_line("2026-08-02T09:00:00Z", "carol", "forward", 5, 5)
    before = one_section([sealed_move])
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    proc, ledger, stream = run_apply(
        tmp_path, before, reset + "\n", engine="99" * 20, stream_text="stale\n",
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert stream.read_bytes() == b"\n", "zero frames: the fresh section is empty"
    assert "u" not in stream.read_text(encoding="ascii"), "sealed frames never re-expanded"
    assert sealed_move in ledger.read_text(encoding="ascii"), "sealed lines preserved verbatim"


def test_moves_after_a_sanctioned_rollover_apply_normally(tmp_path):
    """SPEC 5.5 rule 5: the fresh section's pins match by construction."""
    reset = ledger_line(TS, "alice", "new-game", 1, 20)
    later = ledger_line("2026-08-02T14:10:00Z", "bob", "fire", 1, 21)
    proc, ledger, stream = run_apply(
        tmp_path, one_section(), reset + "\n" + later + "\n", engine="99" * 20,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert stream.read_text(encoding="ascii") == expected_stream_text([("fire", 1)])
    gamelog = import_gamelog()
    log = gamelog.parse_log(ledger.read_text(encoding="ascii"))
    assert [e.issue for e in log.sections[-1].entries] == [21]


def test_sealed_section_with_empty_batch_is_success_with_no_writes(tmp_path):
    """SPEC 5.5 rule 7: a run whose drained moves are all sealed-rejects is a
    SUCCESS with zero ledger appends — the drain rejected everything in-band,
    so apply_moves receives an empty batch. It is not a failure row of the
    write contract: nothing failed and no game state was eligible to change.
    The sealed section's stream is NOT regenerated (rule 1)."""
    before = one_section([ledger_line("2026-08-02T09:00:00Z", "carol", "fire", 1, 5)])
    proc, ledger, stream = run_apply(
        tmp_path, before, "", engine="99" * 20, stream_text="deliberately-stale\n",
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == before, "zero ledger appends"
    assert stream.read_text(encoding="ascii") == "deliberately-stale\n", (
        "a sealed section is never re-simulated, so its stream stands"
    )


def test_sealed_section_with_all_duplicate_moves_is_success_with_no_writes(tmp_path):
    """The other no-admissible-batch shape: every drained line is already in
    the ledger (idempotency key), so nothing lands in the sealed section."""
    already = ledger_line("2026-08-02T09:00:00Z", "carol", "fire", 1, 5)
    before = one_section([already])
    proc, ledger, stream = run_apply(
        tmp_path, before, already + "\n", engine="99" * 20,
        stream_text="deliberately-stale\n",
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ledger.read_text(encoding="ascii") == before
    assert stream.read_text(encoding="ascii") == "deliberately-stale\n"


def test_unsealed_section_with_empty_batch_still_regenerates_the_stream(tmp_path):
    """The rule-1 exemption is scoped to SEALED sections: an unsealed run with
    nothing to append still re-renders, which is the idempotent path doom.yml's
    push-retry loop depends on."""
    before = one_section([ledger_line("2026-08-02T09:00:00Z", "carol", "fire", 1, 5)])
    proc, ledger, stream = run_apply(tmp_path, before, "", stream_text="stale\n")
    assert proc.returncode == 0
    assert ledger.read_text(encoding="ascii") == before
    assert stream.read_text(encoding="ascii") == expected_stream_text([("fire", 1)])


# --- Input validation ---------------------------------------------------------------

def test_missing_ledger_file_is_a_usage_error(tmp_path):
    toolchain = make_toolchain(tmp_path)
    moves = tmp_path / "moves.txt"
    moves.write_text("", encoding="ascii")
    proc = run_script("apply_moves.py", [
        "--ledger", str(tmp_path / "absent.txt"), "--moves", str(moves),
        "--mapping", str(MAPPING_PATH), "--toolchain", str(toolchain),
        "--engine-build-sha256", BUILD_HEX, "--stream", str(tmp_path / "s.txt"),
    ])
    assert proc.returncode == 2


def test_missing_required_argument_is_a_usage_error(tmp_path):
    assert run_script("apply_moves.py", ["--ledger", str(tmp_path / "x")]).returncode == 2


def test_corrupt_ledger_is_exit_5(tmp_path):
    proc, _, _ = run_apply(tmp_path, "this is not a game log\n",
                           ledger_line(TS, "alice", "fire", 1, 11) + "\n")
    assert proc.returncode == 5


def test_non_canonical_moves_line_is_exit_5_with_no_writes(tmp_path):
    before = one_section()
    proc, ledger, stream = run_apply(tmp_path, before, "not a ledger line\n",
                                     stream_text="\n")
    assert proc.returncode == 5
    assert ledger.read_text(encoding="ascii") == before


def test_corrupt_toolchain_json_is_exit_5(tmp_path):
    toolchain = tmp_path / "toolchain.json"
    toolchain.write_text("{not json", encoding="utf-8")
    proc, _, _ = run_apply(tmp_path, one_section(),
                           ledger_line(TS, "alice", "fire", 1, 11) + "\n",
                           toolchain=toolchain)
    assert proc.returncode == 5


def test_empty_ledger_file_is_exit_5(tmp_path):
    proc, _, _ = run_apply(tmp_path, "", ledger_line(TS, "alice", "fire", 1, 11) + "\n")
    assert proc.returncode == 5


# --- Determinism ------------------------------------------------------------------

def test_apply_is_byte_deterministic_for_identical_inputs(tmp_path):
    moves = (
        ledger_line(TS, "alice", "run-forward", 2, 11) + "\n"
        + ledger_line("2026-08-02T14:06:00Z", "bob", "new-game", 1, 12) + "\n"
    )
    a = tmp_path / "a"
    b = tmp_path / "b"
    proc_a, ledger_a, stream_a = run_apply(a, one_section(), moves)
    proc_b, ledger_b, stream_b = run_apply(b, one_section(), moves)
    assert proc_a.returncode == proc_b.returncode == 0
    assert ledger_a.read_bytes() == ledger_b.read_bytes()
    assert stream_a.read_bytes() == stream_b.read_bytes()


def test_written_files_are_ascii_lf_with_exactly_one_trailing_lf(tmp_path):
    proc, ledger, stream = run_apply(
        tmp_path, one_section(), ledger_line(TS, "alice", "fire", 1, 11) + "\n"
    )
    assert proc.returncode == 0
    for blob in (ledger.read_bytes(), stream.read_bytes()):
        assert blob.isascii()
        assert b"\r" not in blob and b"\t" not in blob
        assert blob.endswith(b"\n") and not blob.endswith(b"\n\n")
