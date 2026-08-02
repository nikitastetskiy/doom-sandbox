"""
@spec-handoff
@interface budget.py --mapping PATH --rung {L0,L1,L2} (--size BYTES | --file
    PATH); stdout JSON; exit 0 publish / 10 over-ceiling with a next rung /
    11 over-ceiling at L2 = hard fail, no publish / 12 at-or-below-floor hard
    fail, no publish, NO ladder descent / 2 usage
@behavior
    - Gate order is normative (SPEC 12.1): (1) structural validity — exists,
      non-empty, GIF89a magic — which MAY live in the workflow or in the
      script but must precede any size verdict; (2) floor; (3) ceiling/ladder.
      The floor and ceiling verdicts belong to budget.py, which is what reads
      the mapping
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
    - Every hard failure carries "reason": "floor" | "ceiling" so the workflow
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

def test_zero_byte_gif_never_publishes_and_never_descends(tmp_path):
    """The reported bug: a 0-byte GIF returned publish/exit 0. Whether step 1
    (structural validity) is enforced in the workflow or in the script, a
    0-byte artifact must never publish and must never trigger a re-encode."""
    empty = sparse_file(tmp_path, "empty.gif", 0, magic=b"")
    proc = run_budget("L0", file=empty)
    assert proc.returncode != 0, "a 0-byte GIF must never publish"
    assert proc.returncode != 10, "and must never trigger a ladder descent"


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
