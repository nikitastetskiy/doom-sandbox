"""
@spec-handoff
@interface .github/workflows/doom.yml steps "Encode the GIF through the budget
    ladder" (id: encode) and "Summarize". The encode step walks the mapping
    ladder, runs game/scripts/budget.py per rung, and branches on its exit
    code: 0 publish (output rung=<level>), 10 descend, 11/12/13 hard fail
    (output budget-failure=ceiling|floor|structure), anything else
    budget-failure=unexpected. Every hard fail writes its own $GITHUB_STEP_SUMMARY
    block and its own ::error:: line, and exits 1 with nothing published.
@behavior
    - The step NEVER implements the structural predicate: budget.py owns it and
      the step reports from the verdict JSON, so no normative number (floor,
      ceiling, magic, trailer) is retyped into YAML (SPEC 0.5)
    - 12 and 13 are distinct verdicts on purpose: 13 = not a complete GIF (a
      pipeline/toolchain fault, size irrelevant), 12 = a complete GIF that came
      out degenerate (a palette/pix_fmt fault). They send an operator to two
      different first checks
    - An exit outside budget.py's documented taxonomy (0/2/10/11/12/13) is a
      defect in the GATE, not a verdict about the artifact
    - Summarize is keyed on the STATE SCREEN, not on all_rejected: a batch
      rejected only for grammar or cooldown is ordinary operation and must not
      be reported as degraded mode or claim a swap that did not happen
@edge-cases
    - ffmpeg exits 0 having written no file -> orchestration error, not a
      usage verdict from the gate
    - the ladder ends with nothing publishable -> explicit failure, never a
      silent success
@see game/SPEC.md 0.5/10/12.1; game/scripts/budget.py;
    game/tests/test_budget.py, test_workflow_work_step.py
"""

import pytest
from conftest import (
    BUDGET_CEILING_BYTES,
    BUDGET_FLOOR_BYTES,
    COLLAPSE_SIGNATURE_BYTES,
    LADDER_LEVELS,
    NO_ARTIFACT,
    STILL_FRAME_BYTES,
    assert_fixture_shape,
    load_mapping,
    run_encode_step,
    run_summarize_step,
    sparse_file,
    stub_budget_sandbox,
    workflow_step_run,
)

ENCODE_STEP = "Encode the GIF through the budget ladder"


def publishable_gif(tmp_path):
    """A legitimate single-frame still: structurally complete, inside the band."""
    path = sparse_file(tmp_path, "ok.gif", STILL_FRAME_BYTES)
    return assert_fixture_shape(path, magic=True, trailer=True,
                                size=STILL_FRAME_BYTES)


def over_ceiling_gif(tmp_path):
    size = BUDGET_CEILING_BYTES + 1
    path = sparse_file(tmp_path, "big.gif", size)
    return assert_fixture_shape(path, magic=True, trailer=True, size=size)


def collapsed_gif(tmp_path):
    """A complete GIF that came out degenerate — the recorded palette-collapse
    signature. Structurally valid, which is what separates it from exit 13."""
    path = sparse_file(tmp_path, "tiny.gif", COLLAPSE_SIGNATURE_BYTES)
    assert COLLAPSE_SIGNATURE_BYTES <= BUDGET_FLOOR_BYTES
    return assert_fixture_shape(path, magic=True, trailer=True,
                                size=COLLAPSE_SIGNATURE_BYTES)


def wrong_file_type(tmp_path):
    """A PNG named .gif: no GIF magic, so not the output of a GIF writer."""
    path = sparse_file(tmp_path, "png.gif", 2_400, magic=b"\x89PNG\r\n",
                       trailer=b"\x00")
    return assert_fixture_shape(path, magic=False, trailer=False, size=2_400)


def truncated_gif(tmp_path):
    """A LARGE GIF whose writer never finished: clears floor and ceiling.

    Named apart from wrong_file_type because they are different faults that
    must reach the same verdict — head-only evidence catches one and not the
    other.
    """
    size = STILL_FRAME_BYTES
    path = sparse_file(tmp_path, "cut.gif", size, trailer=b"")
    return assert_fixture_shape(path, magic=True, trailer=False, size=size)


# --- exit 0: publish --------------------------------------------------------
def test_a_publishable_artifact_at_the_first_rung_reports_that_rung(tmp_path):
    result = run_encode_step(tmp_path / "run", [publishable_gif(tmp_path)])
    assert result.returncode == 0, result
    assert result.outputs["rung"] == LADDER_LEVELS[0], result
    assert "budget-failure" not in result.outputs, result


def test_a_published_run_records_no_budget_failure(tmp_path):
    """`budget-failure` unset is what makes the summary's `none` mean "the gate
    returned no hard verdict" rather than "the gate passed"."""
    result = run_encode_step(tmp_path / "run", [publishable_gif(tmp_path)])
    assert result.outputs.get("budget-failure") is None, result


def test_an_over_ceiling_rung_descends_to_the_next_one(tmp_path):
    """Exit 10 is the only non-zero code that continues the ladder."""
    result = run_encode_step(
        tmp_path / "run", [over_ceiling_gif(tmp_path), publishable_gif(tmp_path)]
    )
    assert result.returncode == 0, result
    assert result.outputs["rung"] == LADDER_LEVELS[1], result
    assert f"::notice::{LADDER_LEVELS[0]} exceeds the ceiling" in result.log


def test_the_ladder_is_walked_in_the_mapping_order(tmp_path):
    """The step reads the rungs from the mapping; it does not retype them."""
    levels = [rung["level"] for rung in load_mapping()["budget"]["ladder"]]
    big = over_ceiling_gif(tmp_path)
    result = run_encode_step(tmp_path / "run", [big, big, publishable_gif(tmp_path)])
    assert result.returncode == 0, result
    assert result.outputs["rung"] == levels[-1], result
    for level in levels[:-1]:
        assert f"::notice::{level} exceeds the ceiling" in result.log, result.log


# --- exit 11: over the ceiling at the last rung -----------------------------
def test_over_the_ceiling_at_the_last_rung_reports_the_ceiling_verdict(tmp_path):
    result = run_encode_step(tmp_path / "run", [over_ceiling_gif(tmp_path)])
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "ceiling", result
    assert "rung" not in result.outputs, "nothing was published"


def test_the_ceiling_verdict_writes_its_own_summary_block(tmp_path):
    result = run_encode_step(tmp_path / "run", [over_ceiling_gif(tmp_path)])
    assert "### Refused: over the ceiling at the last ladder rung (exit 11)" in (
        result.summary
    ), result.summary
    assert "| verdict | ceiling (exit 11) |" in result.summary, result.summary


def test_the_ceiling_verdict_reports_the_size_from_the_gates_json(tmp_path):
    """Reported, not retyped: the number in the summary comes from budget.py's
    verdict document, so the ceiling exists in exactly one place."""
    result = run_encode_step(tmp_path / "run", [over_ceiling_gif(tmp_path)])
    assert f"| size | {BUDGET_CEILING_BYTES + 1} bytes |" in result.summary
    assert f"| ceiling | {BUDGET_CEILING_BYTES} bytes |" in result.summary


# --- exit 12: a complete GIF that came out degenerate -----------------------
def test_a_collapsed_encode_reports_the_floor_verdict(tmp_path):
    result = run_encode_step(tmp_path / "run", [collapsed_gif(tmp_path)])
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "floor", result


def test_the_floor_verdict_writes_its_own_summary_block(tmp_path):
    result = run_encode_step(tmp_path / "run", [collapsed_gif(tmp_path)])
    assert "### Refused: the encode collapsed (exit 12, below the publish floor)" in (
        result.summary
    ), result.summary
    assert "| verdict | floor (exit 12) |" in result.summary


def test_the_floor_verdict_reports_the_floor_from_the_gates_json(tmp_path):
    result = run_encode_step(tmp_path / "run", [collapsed_gif(tmp_path)])
    assert f"| size | {COLLAPSE_SIGNATURE_BYTES} bytes |" in result.summary
    assert f"| floor | {BUDGET_FLOOR_BYTES} bytes" in result.summary


def test_the_floor_verdict_sends_the_operator_to_the_palette_path(tmp_path):
    """The whole reason 12 and 13 are two integers: they name different first
    checks. Collapsing them would throw away the distinction."""
    result = run_encode_step(tmp_path / "run", [collapsed_gif(tmp_path)])
    assert "palette" in result.summary, result.summary
    assert "pix_fmt" in result.summary, result.summary


def test_the_floor_verdict_does_not_descend_the_ladder(tmp_path):
    """A smaller re-encode makes a collapse smaller, not better."""
    result = run_encode_step(
        tmp_path / "run", [collapsed_gif(tmp_path), publishable_gif(tmp_path)]
    )
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "floor"
    assert "rung" not in result.outputs, "a later rung must never publish"


# --- exit 13: not the complete output of a GIF writer -----------------------
@pytest.mark.parametrize("kind", ["wrong-file-type", "truncated"])
def test_a_structurally_invalid_artifact_reports_the_structure_verdict(tmp_path, kind):
    artifact = (wrong_file_type if kind == "wrong-file-type" else truncated_gif)(tmp_path)
    result = run_encode_step(tmp_path / "run", [artifact])
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "structure", result


def test_the_structural_verdict_writes_its_own_summary_block(tmp_path):
    result = run_encode_step(tmp_path / "run", [wrong_file_type(tmp_path)])
    assert "### Refused: the artifact is not a complete GIF (exit 13, structural)" in (
        result.summary
    ), result.summary
    assert "| verdict | structural (exit 13) |" in result.summary


def test_the_structural_verdict_sends_the_operator_to_the_pipeline(tmp_path):
    """13's first check is the encoder and its pipe, not the palette — the
    distinction 12 and 13 exist to draw."""
    result = run_encode_step(tmp_path / "run", [wrong_file_type(tmp_path)])
    assert "ffmpeg" in result.summary, result.summary
    assert "palette" not in result.summary, result.summary


def test_a_sub_floor_non_gif_is_reported_as_structural_not_as_a_floor_failure(tmp_path):
    """SPEC 12.1 step precedence: the FIRST violated step alone produces the
    verdict. A 2.4 KB PNG violates both; reporting it as a floor failure would
    send the operator into the palette path for a fault that is not there."""
    artifact = wrong_file_type(tmp_path)
    assert artifact.stat().st_size <= BUDGET_FLOOR_BYTES, (
        "the fixture must be BOTH structurally invalid and sub-floor"
    )
    result = run_encode_step(tmp_path / "run", [artifact])
    assert result.outputs["budget-failure"] == "structure", result
    assert "exit 12" not in result.log, result.log


def test_a_large_truncated_gif_is_refused_even_though_it_clears_both_bounds(tmp_path):
    """The case that makes size the wrong question."""
    artifact = truncated_gif(tmp_path)
    size = artifact.stat().st_size
    assert BUDGET_FLOOR_BYTES < size < BUDGET_CEILING_BYTES, size
    result = run_encode_step(tmp_path / "run", [artifact])
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "structure", result


def test_the_structural_verdict_does_not_descend_the_ladder(tmp_path):
    """A re-encode cannot complete a file the encoder abandoned."""
    result = run_encode_step(
        tmp_path / "run", [truncated_gif(tmp_path), publishable_gif(tmp_path)]
    )
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "structure"
    assert "rung" not in result.outputs


# --- the three hard verdicts stay distinguishable ---------------------------
def test_the_three_hard_verdicts_report_three_distinct_failure_values(tmp_path):
    verdicts = {}
    for name, build in (("ceiling", over_ceiling_gif), ("floor", collapsed_gif),
                        ("structure", wrong_file_type)):
        result = run_encode_step(tmp_path / f"run-{name}", [build(tmp_path / name)])
        verdicts[name] = result.outputs["budget-failure"]
    assert verdicts == {"ceiling": "ceiling", "floor": "floor",
                        "structure": "structure"}, verdicts


@pytest.mark.parametrize(
    ("name", "builder"),
    [("ceiling", over_ceiling_gif), ("floor", collapsed_gif),
     ("structure", wrong_file_type)],
)
def test_every_hard_verdict_says_nothing_was_published(tmp_path, name, builder):
    result = run_encode_step(tmp_path / "run", [builder(tmp_path)])
    assert result.returncode != 0
    assert "nothing is published" in result.log, result.log


@pytest.mark.parametrize(
    ("name", "builder"),
    [("floor", collapsed_gif), ("structure", wrong_file_type)],
)
def test_the_two_pre_push_verdicts_state_the_write_contract_row(tmp_path, name, builder):
    """SPEC section 10: the ledger, the stream and the output branch are
    byte-untouched and every drained move is still an open issue."""
    result = run_encode_step(tmp_path / "run", [builder(tmp_path)])
    assert "byte-untouched" in result.summary, result.summary


# --- an exit outside the taxonomy is a defect in the gate -------------------
@pytest.mark.parametrize("code", [1, 3, 9, 42])
def test_an_undocumented_exit_code_is_reported_as_a_gate_defect(tmp_path, code):
    """Deliberately not a verdict about the artifact.

    budget.py's taxonomy is 0/2/10/11/12/13; anything else means the gate
    itself is broken, and calling it a publication decision would attribute a
    tooling fault to the GIF.
    """
    sandbox = stub_budget_sandbox(tmp_path / "sandbox", code)
    result = run_encode_step(tmp_path / "run", [publishable_gif(tmp_path)],
                             cwd=sandbox)
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "unexpected", result
    assert "outside its documented taxonomy" in result.log, result.log
    assert "defect in the gate itself" in result.log, result.log


def test_the_undocumented_exit_message_names_the_code_it_saw(tmp_path):
    sandbox = stub_budget_sandbox(tmp_path / "sandbox", 42)
    result = run_encode_step(tmp_path / "run", [publishable_gif(tmp_path)],
                             cwd=sandbox)
    assert "exit 42" in result.log, result.log


def test_a_usage_exit_from_the_gate_is_not_treated_as_a_publish(tmp_path):
    """Exit 2 is a malformed INVOCATION, not a malformed artifact, and it is
    outside the branched set — so it must land on the defect arm, never on 0."""
    sandbox = stub_budget_sandbox(tmp_path / "sandbox", 2)
    result = run_encode_step(tmp_path / "run", [publishable_gif(tmp_path)],
                             cwd=sandbox)
    assert result.returncode != 0, result
    assert result.outputs["budget-failure"] == "unexpected", result
    assert "rung" not in result.outputs


# --- orchestration, not the gate --------------------------------------------
def test_an_encoder_that_writes_no_file_fails_before_the_gate_is_asked(tmp_path):
    """budget.py treats a missing --file as a usage error on purpose (a
    malformed invocation, not a malformed artifact), so a vanished output is
    caught here rather than surfacing as a confusing usage verdict."""
    result = run_encode_step(tmp_path / "run", [NO_ARTIFACT])
    assert result.returncode != 0, result
    assert "wrote no output file" in result.log, result.log
    assert result.outputs == {}, result


def encode_step_code_lines():
    """The encode step's executable lines.

    Comments and `echo` prose are excluded on purpose: what the workflow keeps
    is the DIAGNOSIS — the summary block naming `GIF89a` and `0x3B` for a human
    reading a failed run — while the PREDICATE stays in budget.py. Naming a
    constant in operator-facing prose is not a second implementation of it.
    """
    return [line for line in workflow_step_run(ENCODE_STEP).splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_the_encode_step_retypes_no_normative_budget_number():
    """SPEC 0.5: the floor and the ceiling are authored in the mapping and read
    at runtime from the gate's verdict JSON, so neither exists as a literal in
    any language that has no test of its own."""
    magic = load_mapping()["budget"]["structure"]["magic_hex"]
    trailer = load_mapping()["budget"]["structure"]["trailer_hex"]
    for retyped in (str(BUDGET_FLOOR_BYTES), str(BUDGET_CEILING_BYTES), magic,
                    trailer.zfill(2)):
        offenders = [line.strip() for line in encode_step_code_lines()
                     if retyped in line]
        assert offenders == [], (
            f"{retyped!r} is retyped into the workflow; it is authored in "
            f"game/mapping/v1.json and enforced by game/scripts/budget.py: "
            f"{offenders}"
        )


def test_the_encode_step_inspects_no_byte_of_the_artifact_itself():
    """The bash copy removed in 51455c0 read `head -c 6` under a comment
    claiming it caught truncation, while reading no byte past offset 5 — the
    same hole in two places at once. A second copy is not defense in depth."""
    for utility in ("head -c", "xxd", "hexdump", "od -", "cmp "):
        offenders = [line.strip() for line in encode_step_code_lines()
                     if utility in line and "capture.raw" not in line]
        assert offenders == [], (
            f"{utility!r} inspects the artifact in the workflow; SPEC 12.1 "
            f"step 1 has exactly one implementation site: {offenders}"
        )


def test_the_encode_step_has_exactly_one_gate_invocation_site():
    """One call site (walked once per rung), one verdict per artifact. A second
    invocation would be a second place for the branch logic to disagree about
    what the gate said."""
    invocations = [line.strip() for line in encode_step_code_lines()
                   if "budget.py" in line and "echo" not in line]
    assert len(invocations) == 1, invocations
    assert "--file" in invocations[0], invocations[0]


# --- Summarize: the narrative is keyed on the state screen ------------------
def test_the_summary_reports_the_publish_gate_verdict_row(tmp_path):
    result = run_summarize_step(tmp_path, BUDGET_FAILURE="structure")
    assert result.returncode == 0, result
    assert "| publish-gate verdict | structure |" in result.summary, result.summary


def test_the_summary_verdict_row_defaults_to_none(tmp_path):
    """`none` means the gate returned no hard verdict — which includes never
    having been reached. It is NOT an assertion that the artifact was good."""
    result = run_summarize_step(tmp_path)
    assert "| publish-gate verdict | none |" in result.summary, result.summary


@pytest.mark.parametrize("screen", ["SEALED", "LOG_FULL"])
def test_a_state_screen_run_is_reported_as_a_degraded_mode_success(tmp_path, screen):
    result = run_summarize_step(tmp_path, STATE_SCREEN=screen, ALL_REJECTED="true",
                                SWAP_OUTCOME="success")
    assert result.returncode == 0, result
    assert "#### Degraded mode - this run SUCCEEDED" in result.summary, result.summary
    assert f"swapped to `{screen}`" in result.summary, result.summary


def test_a_grammar_only_run_is_not_reported_as_degraded_mode(tmp_path):
    """The recurrence this guards: keying the narrative on all_rejected prints
    "swapped to none" for a live game with an accurate frame on display."""
    result = run_summarize_step(tmp_path, STATE_SCREEN="none", ALL_REJECTED="true")
    assert result.returncode == 0, result
    assert "Degraded mode" not in result.summary, result.summary
    assert "#### This run SUCCEEDED with nothing to apply" in result.summary
    assert "no state screen applies and none was swapped in" in result.summary


def test_a_grammar_only_run_never_claims_a_swap_that_did_not_happen(tmp_path):
    """The exact sentence the first draft would have printed."""
    result = run_summarize_step(tmp_path, STATE_SCREEN="none", ALL_REJECTED="true")
    assert "swapped to `none`" not in result.summary, result.summary
    assert "was swapped to" not in result.summary, result.summary


def test_an_ordinary_run_gets_neither_narrative_block(tmp_path):
    result = run_summarize_step(tmp_path, STATE_SCREEN="none", ALL_REJECTED="false",
                                MOVES="true", RUNG="L0")
    assert result.returncode == 0, result
    assert "Degraded mode" not in result.summary
    assert "SUCCEEDED with nothing to apply" not in result.summary


def test_the_sealed_narrative_names_the_toolchain_pins(tmp_path):
    """The two screens need different operator text: one is a pin mismatch, the
    other is a full log."""
    result = run_summarize_step(tmp_path, STATE_SCREEN="SEALED", ALL_REJECTED="true")
    assert "pins no longer match" in result.summary, result.summary
    assert "frame cap" not in result.summary, result.summary


def test_the_log_full_narrative_names_the_frame_cap(tmp_path):
    result = run_summarize_step(tmp_path, STATE_SCREEN="LOG_FULL", ALL_REJECTED="true")
    assert "frame cap" in result.summary, result.summary
    assert "pins no longer match" not in result.summary, result.summary


@pytest.mark.parametrize("screen", ["SEALED", "LOG_FULL"])
def test_the_degraded_narrative_says_no_operator_action_is_required(tmp_path, screen):
    """A green run with an empty ledger diff and no GIF is otherwise
    indistinguishable at a glance from a run that quietly did nothing."""
    result = run_summarize_step(tmp_path, STATE_SCREEN=screen, ALL_REJECTED="true")
    assert "no operator action is" in result.summary, result.summary


def test_a_quiet_sealed_run_is_still_reported_as_degraded_mode(tmp_path):
    """SPEC 5.8: after the screen becomes a lookup, a sealed section with an
    empty queue reports SEALED while all_rejected is false. The narrative is
    keyed on the screen, so it must still explain the state."""
    result = run_summarize_step(tmp_path, STATE_SCREEN="SEALED", ALL_REJECTED="false",
                                CLOSES="false", MOVES="false")
    assert "#### Degraded mode - this run SUCCEEDED" in result.summary, result.summary
