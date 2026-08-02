"""
@spec-handoff
@interface budget.py --mapping PATH --rung {L0,L1,L2} (--size BYTES | --file
    PATH); stdout JSON; exit 0 publish / 10 over-ceiling with a next rung /
    11 over-ceiling at L2 = hard fail, no publish / 2 usage
@behavior
    - Hard ceiling: 4,000,000 bytes exactly (mapping budget.ceiling_bytes);
      size <= ceiling -> exit 0 and {"publish": true, "rung": R, "size": N}
    - size > ceiling at L0 -> exit 10, {"publish": false, "next": <the L1 entry
      from the mapping ladder>}; at L1 -> exit 10, next = the L2 entry; at L2 ->
      exit 11, {"publish": false, "hard_fail": true, "next": null}
    - Ladder entries (level, tail_seconds, width_px, fps, colors) are read from
      the mapping file, never hardcoded; progression is forward-only L0->L1->L2
@edge-cases
    - size == 4,000,000 -> publish ("exceeds" means strictly greater); unknown
      rung name -> exit 2; --file uses the file's on-disk byte size
@see game/SPEC.md section 12; RFC D7; game/mapping/v1.json budget
"""

import pytest

from conftest import (
    BUDGET_CEILING_BYTES,
    LADDER_LEVELS,
    LADDER_PX_FPS_COLORS,
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
    proc = run_budget("L0", size=1)
    assert proc.returncode == 0


def test_budget_decision_is_deterministic_across_invocations():
    a = run_budget("L1", size=BUDGET_CEILING_BYTES + 500)
    b = run_budget("L1", size=BUDGET_CEILING_BYTES + 500)
    assert (a.returncode, a.stdout) == (b.returncode, b.stdout)
