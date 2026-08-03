"""
@spec-handoff
@interface budget.py --mapping PATH --rung {L0,L1,L2} (--size BYTES | --file
    PATH); stdout JSON; exit 0 publish / 10 over-ceiling with a next rung /
    11 over-ceiling at L2 = hard fail, no publish / 12 at-or-below-floor hard
    fail, no publish, NO ladder descent / 13 structurally invalid artifact,
    hard fail, no publish, NO ladder descent / 2 usage
@behavior
    - Gate order is normative (SPEC 12.1): (1) structural validity; (2) floor;
      (3) ceiling/ladder. budget.py enforces step 1 INDEPENDENTLY AND
      UNCONDITIONALLY before any size verdict — it never assumes the workflow
      gate ran, on the same defense-in-depth precedent as SPEC 5.5 rule 4. The
      workflow gate stays too, because it fails faster and logs better
    - Step 1 positive property: the artifact is the COMPLETE output of a GIF
      writer. Evidence: exists, non-empty, BEGINS with the GIF89a magic AND
      ENDS with the 0x3B trailer — head and tail, because the magic proves a
      writer started and the trailer proves one finished, and neither
      substitutes for the other. Head-only evidence is structurally incapable
      of detecting truncation: truncation removes bytes from the END and the
      magic lives at the START. Both constants are read at runtime from
      mapping budget.structure (magic_hex / trailer_hex), never hardcoded
    - Step precedence: the FIRST violated step alone produces the verdict. An
      artifact may violate several — a 2.4 KB PNG is both structurally invalid
      and sub-floor — and the answer is the lowest-numbered violation: 13,
      never 12. Structural invalidity is the upstream fault; a non-GIF's byte
      count is a property of the wrong file
    - Structural failure is exit 13 with reason "structure", deliberately NOT
      folded into the floor verdict: structural validity is ORTHOGONAL to
      size. Folding is correct only for the 0-byte case where 0 <= floor_bytes
      holds by coincidence; a LARGE malformed artifact (truncated GIF, PNG,
      HTML error page) clears floor and ceiling and would publish
    - --size is NOT a publication path: it asserts a byte count with no
      artifact behind it, so step 1 has nothing to read — structural evidence
      is unavailable, not skipped. Publication decisions come only from --file.
      Hence --size 0 yields 12 while a 0-byte FILE yields 13: two different
      questions, not a contradiction
    - Operator meaning of the two hard-fail integers: 13 = the encoder emitted
      garbage or the wrong file (pipeline/toolchain fault); 12 = the encoder
      emitted a well-formed but degenerate clip (palette/pix_fmt fault).
      Different first debugging step, which is why they are separate
    - A nonexistent --file path stays exit 2: a malformed INVOCATION, not a
      malformed ARTIFACT
    - Hard ceiling: 4,000,000 bytes exactly (mapping budget.ceiling_bytes);
      size <= ceiling -> exit 0 and {"publish": true, "rung": R, "size": N}
    - Hard floor: 16,000 bytes (mapping budget.floor_bytes). size <= floor ->
      exit 12, {"publish": false, "hard_fail": true, "next": null,
      "reason": "floor"} from ANY rung, with no ladder descent: the ladder
      exists to shrink oversized output, so descending on an undersized
      artifact only makes it smaller and cannot repair a collapse. Sub-floor
      means the encode is BROKEN, not mis-tuned
    - size > ceiling at L0 -> exit 10, {"publish": false, "next": <the L1 entry
      from the mapping ladder>}; at L1 -> exit 10, next = the L2 entry; at L2 ->
      exit 11, {"publish": false, "hard_fail": true, "next": null,
      "reason": "ceiling"}
    - Every hard failure carries "reason": "structure" | "floor" | "ceiling" so the workflow
      can branch in YAML and an operator can diagnose without reading logs, and
      reports the floor alongside the ceiling in its output
    - Ladder entries (level, tail_seconds, width_px, fps, colors) are read from
      the mapping file, never hardcoded; progression is forward-only L0->L1->L2
@edge-cases
    - size == 4,000,000 -> publish ("exceeds" means strictly greater), but
      size == 16,000 -> hard fail: the floor is exclusive (publication needs
      size > floor) while the ceiling is inclusive. Do not make them symmetric
    - The legitimate single-frame still (~46 KB, produced by the -nstart
      padded single-frame path) MUST publish; the palette-collapse signature
      (a few KB) MUST NOT. Clip length is not a usable discriminator — GIF
      inter-frame differencing keeps a collapsed clip tiny however long it runs
    - unknown rung name -> exit 2; --file uses the file's on-disk byte size
@see game/SPEC.md sections 12 and 12.1; RFC D7; game/mapping/v1.json budget
"""

import pytest

from conftest import (
    BUDGET_CEILING_BYTES,
    BUDGET_FLOOR_BYTES,
    CLIP_18_FRAME_BYTES,
    COLLAPSE_SIGNATURE_BYTES,
    GIF89A_MAGIC,
    assert_fixture_shape,
    LADDER_LEVELS,
    LADDER_PX_FPS_COLORS,
    STILL_FRAME_BYTES,
    json_stdout,
    load_mapping,
    run_budget,
    sparse_file,
)


def ladder_by_level():
    return {entry["level"]: entry for entry in load_mapping()["budget"]["ladder"]}


# --- Ceiling: one exact constant --------------------------------------------

def test_size_exactly_at_the_4_000_000_byte_ceiling_publishes():
    proc = run_budget("L2", size=BUDGET_CEILING_BYTES)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    out = json_stdout(proc)
    assert out["publish"] is True
    assert out["rung"] == "L2"
    assert out["size"] == 4_000_000


def test_size_one_byte_over_the_ceiling_at_l2_hard_fails_no_publish():
    proc = run_budget("L2", size=BUDGET_CEILING_BYTES + 1)
    assert proc.returncode == 11
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["hard_fail"] is True
    assert out["next"] is None


def test_small_gif_publishes_at_l0_without_descending_the_ladder():
    proc = run_budget("L0", size=150_000)
    assert proc.returncode == 0
    out = json_stdout(proc)
    assert out["publish"] is True and out["rung"] == "L0"


# --- Ladder progression L0 -> L1 -> L2 --------------------------------------

def test_over_ceiling_at_l0_directs_re_encode_at_the_l1_mapping_entry():
    proc = run_budget("L0", size=BUDGET_CEILING_BYTES + 1)
    assert proc.returncode == 10
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["next"] == ladder_by_level()["L1"]


def test_over_ceiling_at_l1_directs_re_encode_at_the_l2_mapping_entry():
    proc = run_budget("L1", size=5_333_000)
    assert proc.returncode == 10
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["next"] == ladder_by_level()["L2"]


def test_unknown_rung_name_is_a_usage_error():
    assert run_budget("L3", size=100).returncode == 2


def test_missing_size_and_file_is_a_usage_error():
    assert run_budget("L0").returncode == 2


# --- File mode ---------------------------------------------------------------

def test_file_mode_uses_the_on_disk_byte_size_over_ceiling(tmp_path):
    over = sparse_file(tmp_path, "over.gif", BUDGET_CEILING_BYTES + 1)
    proc = run_budget("L2", file=over)
    assert proc.returncode == 11


def test_file_mode_uses_the_on_disk_byte_size_at_ceiling(tmp_path):
    at = sparse_file(tmp_path, "at.gif", BUDGET_CEILING_BYTES)
    proc = run_budget("L2", file=at)
    assert proc.returncode == 0
    assert json_stdout(proc)["publish"] is True


def test_missing_file_is_a_usage_error(tmp_path):
    assert run_budget("L0", file=tmp_path / "absent.gif").returncode == 2


# --- Mapping consumption: constants come from the file ----------------------

def test_mapping_budget_constants_match_the_normative_spec_shape():
    """Ceiling and ladder shape are normative (RFC D7): 4,000,000 bytes, three
    rungs L0->L1->L2, px/fps/colors 320/12/128 -> 320/12/128 -> 256/10/64.
    tail_seconds is the plan-tunable constant and is intentionally asserted
    only for monotonic non-increase (E2's authorized re-tune adjusts it).
    Rides with a script call so the test is red until E4."""
    budget = load_mapping()["budget"]
    assert budget["ceiling_bytes"] == BUDGET_CEILING_BYTES == 4_000_000
    levels = [entry["level"] for entry in budget["ladder"]]
    assert tuple(levels) == LADDER_LEVELS == ("L0", "L1", "L2")
    tails = []
    for entry in budget["ladder"]:
        px, fps, colors = LADDER_PX_FPS_COLORS[entry["level"]]
        assert entry["width_px"] == px
        assert entry["fps"] == fps
        assert entry["colors"] == colors
        tails.append(entry["tail_seconds"])
    assert tails == sorted(tails, reverse=True), (
        "ladder tails must not increase down the ladder"
    )
    assert all(t > 0 for t in tails)
    assert budget["floor_bytes"] == BUDGET_FLOOR_BYTES
    # a publishable size must sit above the floor as well as under the ceiling
    proc = run_budget("L0", size=STILL_FRAME_BYTES)
    assert proc.returncode == 0


# --- Floor: a sub-floor artifact is broken, not small (SPEC 12.1) ---------------

def test_size_exactly_at_the_floor_hard_fails_with_exit_12():
    """The floor is EXCLUSIVE — publication requires size > floor_bytes —
    unlike the inclusive ceiling. Asserted deliberately so the two boundaries
    are never 'tidied' into matching forms."""
    proc = run_budget("L0", size=BUDGET_FLOOR_BYTES)
    assert proc.returncode == 12, (proc.stdout, proc.stderr)
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["hard_fail"] is True
    assert out["next"] is None
    assert out["reason"] == "floor"


def test_size_one_byte_below_the_floor_hard_fails():
    proc = run_budget("L0", size=BUDGET_FLOOR_BYTES - 1)
    assert proc.returncode == 12
    assert json_stdout(proc)["reason"] == "floor"


def test_size_one_byte_above_the_floor_publishes():
    proc = run_budget("L0", size=BUDGET_FLOOR_BYTES + 1)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json_stdout(proc)["publish"] is True


def test_palette_collapse_signature_is_rejected():
    """The recorded collapse is a WELL-FORMED few-KB GIF: neither magic bytes
    nor the ceiling catches it. The floor is the only gate that does."""
    proc = run_budget("L0", size=COLLAPSE_SIGNATURE_BYTES)
    assert proc.returncode == 12
    out = json_stdout(proc)
    assert out["publish"] is False and out["reason"] == "floor"


# --- Acceptance direction: the floor must not reject legitimate artifacts -------

def test_legitimate_single_frame_still_is_accepted():
    """THE trap. Rin's -nstart fix creates a padded single-frame path (ffmpeg
    cannot write a one-frame GIF), whose legitimate output is ~46 KB. A floor
    chosen or tested carelessly rejects exactly the output that fix produces —
    two individually correct changes combining into a broken system."""
    proc = run_budget("L0", size=STILL_FRAME_BYTES)
    assert proc.returncode == 0, (
        f"the legitimate ~46 KB single-frame still must publish: {proc.stdout!r}"
    )
    out = json_stdout(proc)
    assert out["publish"] is True
    assert out["size"] == STILL_FRAME_BYTES


def test_legitimate_18_frame_clip_is_accepted():
    proc = run_budget("L0", size=CLIP_18_FRAME_BYTES)
    assert proc.returncode == 0
    assert json_stdout(proc)["publish"] is True


def test_the_floor_sits_strictly_inside_the_discriminating_band():
    """SPEC 12.1's band: collapse signature < floor < smallest legitimate
    artifact. If a future retune inverts either side, the floor is wrong."""
    assert COLLAPSE_SIGNATURE_BYTES < BUDGET_FLOOR_BYTES < STILL_FRAME_BYTES
    assert BUDGET_FLOOR_BYTES < BUDGET_CEILING_BYTES
    reject = run_budget("L0", size=COLLAPSE_SIGNATURE_BYTES)
    accept = run_budget("L0", size=STILL_FRAME_BYTES)
    assert reject.returncode == 12 and accept.returncode == 0


def test_legitimate_still_is_accepted_from_every_rung(tmp_path):
    for rung in LADDER_LEVELS:
        proc = run_budget(rung, file=sparse_file(tmp_path, f"still-{rung}.gif",
                                                 STILL_FRAME_BYTES))
        assert proc.returncode == 0, f"{rung}: legitimate still must publish"


# --- No ladder descent on a floor violation -------------------------------------

@pytest.mark.parametrize("rung", LADDER_LEVELS)
def test_floor_violation_never_descends_the_ladder(rung):
    """Descending a rung on an undersized artifact makes it smaller still: it
    cannot repair a collapse and merely burns encodes."""
    proc = run_budget(rung, size=COLLAPSE_SIGNATURE_BYTES)
    assert proc.returncode == 12, f"{rung} must hard-fail, never re-encode"
    out = json_stdout(proc)
    assert out["next"] is None, "a floor violation offers no next rung"
    assert out["hard_fail"] is True
    assert out["reason"] == "floor"


def test_floor_verdict_precedes_the_ceiling_and_ladder_verdict():
    """Gate order (SPEC 12.1): floor is step 2, ceiling/ladder step 3. A
    sub-floor size at L0 must yield the floor verdict, never a rung descent."""
    proc = run_budget("L0", size=COLLAPSE_SIGNATURE_BYTES)
    assert proc.returncode == 12, "not 10 — the floor is decided before the ladder"
    assert json_stdout(proc)["reason"] == "floor"


# --- reason on both hard-fail directions ------------------------------------------

def test_ceiling_hard_fail_reports_reason_ceiling():
    proc = run_budget("L2", size=BUDGET_CEILING_BYTES + 1)
    assert proc.returncode == 11
    out = json_stdout(proc)
    assert out["reason"] == "ceiling"
    assert out["hard_fail"] is True and out["next"] is None


def test_the_two_hard_fail_directions_are_distinguishable():
    """Both are hard_fail with next=null; only `reason` tells them apart, which
    is what lets the workflow branch and an operator diagnose without logs."""
    floor = json_stdout(run_budget("L2", size=BUDGET_FLOOR_BYTES))
    ceiling = json_stdout(run_budget("L2", size=BUDGET_CEILING_BYTES + 1))
    assert floor["hard_fail"] is ceiling["hard_fail"] is True
    assert floor["next"] is ceiling["next"] is None
    assert floor["reason"] == "floor"
    assert ceiling["reason"] == "ceiling"
    assert floor["reason"] != ceiling["reason"]


@pytest.mark.parametrize(
    ("case_id", "size", "code"),
    [("floor", BUDGET_FLOOR_BYTES, 12), ("ceiling", BUDGET_CEILING_BYTES + 1, 11)],
    ids=["floor", "ceiling"],
)
def test_hard_fail_output_reports_the_floor_alongside_the_ceiling(case_id, size, code):
    proc = run_budget("L2", size=size)
    assert proc.returncode == code
    out = json_stdout(proc)
    assert out["floor"] == BUDGET_FLOOR_BYTES
    assert out["ceiling"] == BUDGET_CEILING_BYTES


# --- Degenerate artifacts (the bug that motivated the floor) ----------------------

def test_zero_byte_gif_is_a_structural_failure(tmp_path):
    """The reported bug: a 0-byte GIF returned publish/exit 0. budget.py
    enforces structure independently and unconditionally (SPEC 12.1 step 1) —
    it never assumes the workflow gate ran."""
    empty = assert_fixture_shape(
        sparse_file(tmp_path, "empty.gif", 0, magic=b""),
        magic=False, trailer=False, size=0,
    )
    proc = run_budget("L0", file=empty)
    assert proc.returncode == 13, (proc.stdout, proc.stderr)
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["hard_fail"] is True
    assert out["next"] is None
    assert out["reason"] == "structure"


def test_large_truncated_gif_is_rejected(tmp_path):
    """THE headline regression (SPEC 12.1 instance five).

    A valid GIF89a header with an unterminated body, comfortably above the
    floor: this is the artifact that actually published to Nik's profile. It
    clears the floor, clears the ceiling, and carries the magic, so head-only
    evidence returned exit 0 / publish: true. Only the trailer check rejects
    it. The fixture is verified to BE a truncated GIF before the gate is
    exercised — magic present, trailer absent — because a test that describes
    truncation while stripping the magic asserts a different predicate than
    its name claims.
    """
    truncated = assert_fixture_shape(
        sparse_file(tmp_path, "truncated.gif", 1_500_000, trailer=b""),
        magic=True, trailer=False, size=1_500_000,
    )
    assert BUDGET_FLOOR_BYTES < 1_500_000 < BUDGET_CEILING_BYTES, (
        "the fixture must sit inside the publishable size band, so neither "
        "the floor nor the ceiling can be what rejects it"
    )
    proc = run_budget("L0", file=truncated)
    assert proc.returncode == 13, (
        f"a 1.5 MB truncated GIF must fail structurally, not publish: {proc.stdout!r}"
    )
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["reason"] == "structure", (
        "and must not be mislabelled 'floor' — it is nowhere near the floor"
    )
    assert out["next"] is None, "no ladder descent repairs a truncated file"


def test_wrong_file_entirely_named_gif_is_rejected(tmp_path):
    """The other half of the structural class, and a DIFFERENT predicate from
    truncation: a file that never was a GIF (wrong magic). Caught even by
    head-only evidence — kept as its own test so the truncation case above is
    not credited with covering it, or vice versa.
    """
    bogus = assert_fixture_shape(
        sparse_file(tmp_path, "not-a.gif", 1_500_000, magic=b""),
        magic=False, trailer=True, size=1_500_000,
    )
    proc = run_budget("L0", file=bogus)
    assert proc.returncode == 13, (proc.stdout, proc.stderr)
    out = json_stdout(proc)
    assert out["publish"] is False
    assert out["reason"] == "structure"
    assert out["next"] is None


def test_html_error_page_saved_as_gif_is_rejected(tmp_path):
    """A failed fetch that wrote an error page to the artifact path. Wrong
    magic, not truncation."""
    path = tmp_path / "error.gif"
    path.write_bytes(b"<!DOCTYPE html>\n<html><body>504 Gateway Timeout</body></html>\n"
                     + b"\0" * 100_000)
    assert_fixture_shape(path, magic=False, trailer=False)
    proc = run_budget("L0", file=path)
    assert proc.returncode == 13
    assert json_stdout(proc)["reason"] == "structure"


@pytest.mark.parametrize("rung", LADDER_LEVELS)
@pytest.mark.parametrize(
    ("kind", "kwargs", "shape"),
    [
        ("truncated", {"trailer": b""}, {"magic": True, "trailer": False}),
        ("wrong-magic", {"magic": b""}, {"magic": False, "trailer": True}),
    ],
    ids=["truncated", "wrong-magic"],
)
def test_structural_failure_never_descends_the_ladder(rung, kind, kwargs, shape, tmp_path):
    bogus = assert_fixture_shape(
        sparse_file(tmp_path, f"{kind}-{rung}.gif", 1_500_000, **kwargs), **shape
    )
    proc = run_budget(rung, file=bogus)
    assert proc.returncode == 13, f"{rung}/{kind} must hard-fail structurally"
    assert json_stdout(proc)["next"] is None


def test_the_three_hard_fail_reasons_are_distinct(tmp_path):
    """13 = the encoder emitted garbage or the wrong file (pipeline/toolchain
    fault); 12 = a well-formed but degenerate clip (palette/pix_fmt fault);
    11 = genuinely oversized. Different first debugging step, so the operator
    must be able to tell them apart from the verdict alone."""
    truncated = assert_fixture_shape(
        sparse_file(tmp_path, "s.gif", 1_500_000, trailer=b""),
        magic=True, trailer=False,
    )
    structure = run_budget("L0", file=truncated)
    floor = run_budget("L2", size=BUDGET_FLOOR_BYTES)
    ceiling = run_budget("L2", size=BUDGET_CEILING_BYTES + 1)
    codes = (structure.returncode, floor.returncode, ceiling.returncode)
    assert codes == (13, 12, 11)
    reasons = tuple(json_stdout(p)["reason"] for p in (structure, floor, ceiling))
    assert reasons == ("structure", "floor", "ceiling")
    assert len(set(reasons)) == 3


# --- Step precedence: the first violated step alone produces the verdict --------

def test_small_truncated_file_is_structural_not_floor(tmp_path):
    """RE-PIN. Under the head-only predicate this artifact was a floor
    violation (12) and that was correct. Under the ratified head-and-tail
    predicate it violates step 1, and step 1 outranks step 2: the verdict is
    13. Reporting it as 'floor' would send the operator into the palette /
    pix_fmt path for a problem that is not in the encoder's colour handling.
    """
    truncated = assert_fixture_shape(
        sparse_file(tmp_path, "small-truncated.gif", COLLAPSE_SIGNATURE_BYTES,
                    trailer=b""),
        magic=True, trailer=False,
    )
    assert COLLAPSE_SIGNATURE_BYTES < BUDGET_FLOOR_BYTES, "fixture is sub-floor"
    proc = run_budget("L0", file=truncated)
    assert proc.returncode == 13, "structural violation outranks the floor"
    assert json_stdout(proc)["reason"] == "structure"


def test_artifact_violating_both_structure_and_floor_reports_structure(tmp_path):
    """SPEC 12.1: a 2.4 KB PNG is both structurally invalid and sub-floor; the
    verdict is the lowest-numbered violated step, 13, never 12."""
    png_ish = assert_fixture_shape(
        sparse_file(tmp_path, "tiny.png", 2_400, magic=b""),
        magic=False, trailer=True,
    )
    assert 2_400 < BUDGET_FLOOR_BYTES
    proc = run_budget("L0", file=png_ish)
    assert proc.returncode == 13
    assert json_stdout(proc)["reason"] == "structure"


def test_structurally_valid_sub_floor_file_still_reports_floor(tmp_path):
    """The precedence rule must not swallow the floor: an artifact that PASSES
    step 1 and fails step 2 is still a floor violation (12), which is what
    keeps the palette-collapse diagnosis intact."""
    collapsed = assert_fixture_shape(
        sparse_file(tmp_path, "collapsed.gif", COLLAPSE_SIGNATURE_BYTES),
        magic=True, trailer=True,
    )
    proc = run_budget("L0", file=collapsed)
    assert proc.returncode == 12, "a complete but degenerate clip is a floor fault"
    assert json_stdout(proc)["reason"] == "floor"


# --- --size is a diagnostic entry point, not a publication path -----------------

def test_size_mode_cannot_produce_a_publication_decision(tmp_path):
    """SPEC 12.1: --size asserts a byte count with no artifact behind it, so
    step 1 has nothing to read — structural evidence is UNAVAILABLE, not
    skipped. Publication decisions are made only from --file. This is why
    --size 0 yields 12 while a 0-byte FILE yields 13: two different questions.
    """
    by_size = run_budget("L0", size=0)
    assert by_size.returncode == 12, "--size asks only 'is this below the floor?'"
    assert json_stdout(by_size)["reason"] == "floor"

    empty_file = assert_fixture_shape(
        sparse_file(tmp_path, "empty.gif", 0, magic=b""),
        magic=False, trailer=False,
    )
    by_file = run_budget("L0", file=empty_file)
    assert by_file.returncode == 13, "--file asks 'is this artifact a GIF?'"
    assert json_stdout(by_file)["reason"] == "structure"
    assert by_size.returncode != by_file.returncode, (
        "the same byte count reaches different verdicts through the two entry "
        "points, and that is the specified behaviour, not a contradiction"
    )


def test_size_mode_never_reports_a_structural_verdict():
    """--size can never emit reason 'structure' — it has no artifact to read."""
    for size in (0, COLLAPSE_SIGNATURE_BYTES, STILL_FRAME_BYTES,
                 BUDGET_CEILING_BYTES + 1):
        proc = run_budget("L0", size=size)
        assert proc.returncode != 13, f"--size {size} must not yield a structural verdict"
        out = json_stdout(proc)
        assert out.get("reason") != "structure"


def test_a_valid_gif_header_passes_the_structural_gate(tmp_path):
    """The acceptance direction of the structural gate: a well-formed artifact
    in the publishable band must still publish."""
    good = sparse_file(tmp_path, "good.gif", STILL_FRAME_BYTES)
    assert good.read_bytes()[:6] == GIF89A_MAGIC
    proc = run_budget("L0", file=good)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json_stdout(proc)["publish"] is True


def test_nonexistent_file_stays_a_usage_error_not_a_structural_failure(tmp_path):
    """SPEC 12.1 preserves this boundary explicitly: a missing path is a
    malformed INVOCATION (exit 2), not a malformed ARTIFACT (exit 13)."""
    proc = run_budget("L0", file=tmp_path / "absent.gif")
    assert proc.returncode == 2, "a nonexistent --file path is a usage error"


def test_zero_byte_size_argument_hard_fails_on_the_floor():
    proc = run_budget("L0", size=0)
    assert proc.returncode == 12
    out = json_stdout(proc)
    assert out["publish"] is False and out["reason"] == "floor"


def test_sub_floor_file_mode_agrees_with_size_mode(tmp_path):
    collapsed = sparse_file(tmp_path, "collapsed.gif", COLLAPSE_SIGNATURE_BYTES)
    by_file = run_budget("L0", file=collapsed)
    by_size = run_budget("L0", size=COLLAPSE_SIGNATURE_BYTES)
    assert by_file.returncode == by_size.returncode == 12
    assert json_stdout(by_file)["reason"] == json_stdout(by_size)["reason"] == "floor"


def test_budget_decision_is_deterministic_across_invocations():
    a = run_budget("L1", size=BUDGET_CEILING_BYTES + 500)
    b = run_budget("L1", size=BUDGET_CEILING_BYTES + 500)
    assert (a.returncode, a.stdout) == (b.returncode, b.stdout)
