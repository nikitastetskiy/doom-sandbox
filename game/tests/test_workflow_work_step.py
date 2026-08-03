"""
@spec-handoff
@interface .github/workflows/doom.yml step "Decide whether there is work"
    (id: work). Reads ${RUNNER_TEMP}/moves.txt and ${RUNNER_TEMP}/actions.json
    (drain.py's out-moves / out-actions) plus ${MAPPING}; writes exactly four
    keys to $GITHUB_OUTPUT — moves, closes, all_rejected, state_screen — and
    exits 0, or exits 1 having written nothing.
@behavior
    - moves = moves.txt is non-empty; closes = post_push is non-empty
    - drained counts post_push entries whose reason is NOT "duplicate";
      applied counts reason == "applied"; all_rejected = drained > 0 AND
      applied == 0 (a SUCCESS condition, and after SPEC 5.8 a SUMMARY signal
      only — it no longer selects a screen)
    - every reason is validated against mapping reason_codes (SPEC 5.7 closed
      enum) BEFORE the arithmetic; the enum is read from the mapping, never
      retyped into YAML, and player-visible prose is never matched
    - ledger lines (wc -l moves.txt) must equal applied, checked pre-push
    - state_screen is a LOOKUP of the SPEC 5.8 `.section.state` field:
      sealed -> SEALED, capped -> LOG_FULL, open -> "". The step maps a value
      it was handed; it never re-derives the pin or cap comparison (SPEC 0.5)
      and never consults all_rejected to decide it
@edge-cases
    - reason key absent / null -> refused and reported as `null` (jq `join`
      renders both as "", which would wave the defect through; `tojson` does not)
    - `.section.state` absent or outside mapping section_states -> hard fail,
      by the same rule that refuses an unknown reason code
    - quiet sealed batch (nothing drained) -> SEALED with all_rejected false
    - grammar/cooldown-only batch -> all_rejected TRUE with NO state screen
@see game/SPEC.md 0.5/5.5/5.7/5.8/10; game/scripts/drain.py;
    game/tests/test_workflow_contract.py, test_workflow_publish_verdicts.py
"""

import pytest
from conftest import (
    NO_REASON_FIELD,
    NO_SECTION_FIELD,
    SCREEN_FOR_SECTION_STATE,
    SECTION_CAPPED,
    SECTION_OPEN,
    SECTION_SEALED,
    STATE_SWAP_STEP,
    WORK_STEP_OUTPUTS,
    assert_drain_plan_shape,
    close_plan,
    ledger_line,
    load_mapping,
    make_issue,
    make_section_text,
    reason_codes_of,
    run_drain_then_work_step,
    run_work_step,
    run_workflow_step,
    sealed_section_text,
    section_state_of,
    workflow_step_field,
    workflow_step_run,
    write_mapping,
)

TS = "2026-08-02T12:00:00Z"
EMPTY_LEDGER = make_section_text([], n=1)

# SPEC 5.7 / 5.8 closed enums, read from the mapping so this file retypes nothing.
REASON_CODES = load_mapping()["reason_codes"]
SECTION_STATES = load_mapping()["section_states"]

# 741 x (run-forward 18 frames x9) = 120,042 >= the 120,000 section cap.
AT_CAP_LINES = [
    ledger_line("2026-07-30T10:00:00Z", "grinder", "run-forward", 9, i)
    for i in range(1, 742)
]


def at_cap_ledger():
    return make_section_text(AT_CAP_LINES, n=1)


def sealed_at_cap_ledger():
    """A section that is sealed AND at its frame cap — both conditions at once."""
    return sealed_section_text(AT_CAP_LINES, n=1)


# --- Real-drain scenarios ---------------------------------------------------
# `shape` is asserted against the REAL drain output before the step's verdict is
# judged, so a scenario can never quietly stop being the case it is named for.
# `section` is the SPEC 5.8 state the drain must report for that scenario; the
# screen is its lookup, never a second derivation.
SCENARIOS = {
    "empty-sweep": dict(
        issues=[], ledger=EMPTY_LEDGER,
        shape=dict(reasons=[], applied=0, drained=0),
        section=SECTION_OPEN,
        expect=dict(moves="false", closes="false", all_rejected="false"),
    ),
    "ordinary-batch": dict(
        issues=[make_issue(11, "doom: forward", TS),
                make_issue(12, "doom: fire x3", TS)],
        ledger=EMPTY_LEDGER,
        shape=dict(reasons=["applied"], applied=2, drained=2),
        section=SECTION_OPEN,
        expect=dict(moves="true", closes="true", all_rejected="false"),
    ),
    "duplicate-only": dict(
        issues=[make_issue(5, "doom: fire", TS), make_issue(6, "doom: back", TS)],
        ledger=make_section_text([ledger_line(TS, "old", "fire", 1, 5),
                                  ledger_line(TS, "old", "back", 1, 6)], n=1),
        shape=dict(reasons=["duplicate"], applied=0, drained=0),
        section=SECTION_OPEN,
        expect=dict(moves="false", closes="true", all_rejected="false"),
    ),
    "grammar-only": dict(
        issues=[make_issue(21, "doom: jump", TS), make_issue(22, "doom: fire x99", TS)],
        ledger=EMPTY_LEDGER,
        shape=dict(reasons=["grammar"], applied=0, drained=2),
        section=SECTION_OPEN,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
    "cooldown-only": dict(
        issues=[make_issue(31, "doom: new game", "2026-07-30T10:10:00Z")],
        ledger=make_section_text(
            [ledger_line("2026-07-30T10:00:00Z", "bob", "new-game", 1, 7)], n=1),
        shape=dict(reasons=["cooldown"], applied=0, drained=1),
        section=SECTION_OPEN,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
    "sealed": dict(
        issues=[make_issue(41, "doom: fire", TS)],
        ledger=sealed_section_text([ledger_line(TS, "earlier", "fire", 1, 5)]),
        shape=dict(reasons=["sealed"], applied=0, drained=1),
        section=SECTION_SEALED,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
    "sealed-then-rescued": dict(
        issues=[make_issue(51, "doom: fire", TS),
                make_issue(52, "doom: new game", TS)],
        ledger=sealed_section_text([ledger_line(TS, "earlier", "fire", 1, 5)]),
        shape=dict(reasons=["sealed", "applied"], applied=1, drained=2),
        section=SECTION_OPEN,
        expect=dict(moves="true", closes="true", all_rejected="false"),
    ),
    "sealed-and-duplicate": dict(
        issues=[make_issue(5, "doom: fire", TS), make_issue(61, "doom: back", TS)],
        ledger=sealed_section_text([ledger_line(TS, "earlier", "fire", 1, 5)]),
        shape=dict(reasons=["duplicate", "sealed"], applied=0, drained=1),
        section=SECTION_SEALED,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
    "sealed-with-only-duplicates": dict(
        issues=[make_issue(5, "doom: fire", TS)],
        ledger=sealed_section_text([ledger_line(TS, "earlier", "fire", 1, 5)]),
        shape=dict(reasons=["duplicate"], applied=0, drained=0),
        section=SECTION_SEALED,
        expect=dict(moves="false", closes="true", all_rejected="false"),
    ),
    "sealed-and-nobody-is-playing": dict(
        issues=[], ledger=sealed_section_text([ledger_line(TS, "e", "fire", 1, 5)]),
        shape=dict(reasons=[], applied=0, drained=0),
        section=SECTION_SEALED,
        expect=dict(moves="false", closes="false", all_rejected="false"),
    ),
    "section-cap": dict(
        issues=[make_issue(9001, "doom: forward", TS)],
        ledger=at_cap_ledger(),
        shape=dict(reasons=["section-cap"], applied=0, drained=1),
        section=SECTION_CAPPED,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
    "capped-and-nobody-is-playing": dict(
        issues=[], ledger=at_cap_ledger(),
        shape=dict(reasons=[], applied=0, drained=0),
        section=SECTION_CAPPED,
        expect=dict(moves="false", closes="false", all_rejected="false"),
    ),
    "cap-then-reset": dict(
        issues=[make_issue(9001, "doom: forward", TS),
                make_issue(9002, "doom: new game", TS)],
        ledger=at_cap_ledger(),
        shape=dict(reasons=["section-cap", "applied"], applied=1, drained=2),
        section=SECTION_OPEN,
        expect=dict(moves="true", closes="true", all_rejected="false"),
    ),
    "cap-and-cooldown": dict(
        issues=[make_issue(9001, "doom: forward", "2026-07-30T10:10:00Z"),
                make_issue(9002, "doom: new game", "2026-07-30T10:10:00Z")],
        ledger=make_section_text(
            AT_CAP_LINES + [ledger_line("2026-07-30T10:00:00Z", "bob", "new-game",
                                        1, 8000)], n=1),
        shape=dict(reasons=["section-cap", "cooldown"], applied=0, drained=2),
        section=SECTION_CAPPED,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
    "applied-with-duplicates": dict(
        issues=[make_issue(5, "doom: fire", TS), make_issue(71, "doom: back", TS)],
        ledger=make_section_text([ledger_line(TS, "old", "fire", 1, 5)], n=1),
        shape=dict(reasons=["duplicate", "applied"], applied=1, drained=1),
        section=SECTION_OPEN,
        expect=dict(moves="true", closes="true", all_rejected="false"),
    ),
    # 9500 is deliberately outside AT_CAP_LINES' issue range (1..741): a
    # colliding number arrives as `duplicate` and the scenario silently stops
    # being the case it is named for.
    "sealed-at-its-cap": dict(
        issues=[make_issue(9500, "doom: forward", TS)],
        ledger=sealed_at_cap_ledger(),
        shape=dict(reasons=["sealed"], applied=0, drained=1),
        section=SECTION_SEALED,
        expect=dict(moves="false", closes="true", all_rejected="true"),
    ),
}


@pytest.fixture(scope="session")
def drive(tmp_path_factory):
    """Run the real drain for a scenario, assert it IS that case, run the step.

    Computed once per scenario and shared read-only. drain.py reads no wall
    clock and no network and the step reads only its files, so a scenario is a
    pure function of committed inputs — recomputing it four times bought
    nothing but seconds. The shape assertion lives at construction, which is
    the assert_fixture_shape discipline: a scenario that stops being the case
    it is named for fails every test that uses it, loudly, at the fixture.
    """
    cache = {}

    def get(scenario_id):
        if scenario_id not in cache:
            case = SCENARIOS[scenario_id]
            base = tmp_path_factory.mktemp(scenario_id.replace("-", "_")[:24])
            actions, moves_text, result = run_drain_then_work_step(
                base, case["issues"], case["ledger"]
            )
            assert_drain_plan_shape(actions, moves_text, **case["shape"])
            cache[scenario_id] = (case, actions, result)
        return cache[scenario_id]

    return get


@pytest.mark.parametrize("scenario_id", list(SCENARIOS), ids=list(SCENARIOS))
def test_the_step_computes_moves_closes_and_all_rejected_from_real_drain_output(
    drive, scenario_id
):
    """The three reason-code-derived outputs, over the drain's real plan."""
    case, _, result = drive(scenario_id)
    assert result.returncode == 0, result
    got = {key: result.outputs[key] for key in case["expect"]}
    assert got == case["expect"], result


@pytest.mark.parametrize("scenario_id", list(SCENARIOS), ids=list(SCENARIOS))
def test_the_step_writes_exactly_the_four_documented_output_keys(drive, scenario_id):
    """Four, not three: all_rejected and state_screen answer different questions
    and, after SPEC 5.8, are computed from different evidence."""
    _, _, result = drive(scenario_id)
    assert set(result.outputs) == WORK_STEP_OUTPUTS, result


@pytest.mark.parametrize("scenario_id", list(SCENARIOS), ids=list(SCENARIOS))
def test_the_drain_reports_the_section_state_each_scenario_is_named_for(
    drive, scenario_id
):
    """The producer half of the screen contract (SPEC 5.8), end to end."""
    case, actions, _ = drive(scenario_id)
    assert section_state_of(actions) == case["section"]


@pytest.mark.parametrize("scenario_id", list(SCENARIOS), ids=list(SCENARIOS))
def test_the_state_screen_is_the_lookup_of_the_section_state_the_drain_reported(
    drive, scenario_id
):
    """Producer and consumer bound together on real output.

    Not "the expected screen for this scenario" — the screen the drain's OWN
    reported state maps to. If the two ever disagree the step is deriving the
    screen itself, which is the SPEC 0.5 violation this contract removed.
    """
    _, actions, result = drive(scenario_id)
    expected = SCREEN_FOR_SECTION_STATE[section_state_of(actions)]
    assert result.outputs["state_screen"] == expected, result


# --- The screen is a lookup, not a predicate (SPEC 5.8) ---------------------
@pytest.mark.parametrize("state", list(SCREEN_FOR_SECTION_STATE))
def test_each_section_state_selects_its_mapped_screen(tmp_path, state):
    result = run_work_step(tmp_path, close_plan((1, "grammar"), section=state))
    assert result.returncode == 0, result
    assert result.outputs["state_screen"] == SCREEN_FOR_SECTION_STATE[state], result


def test_a_quiet_sealed_run_still_reports_the_sealed_screen(tmp_path):
    """The case SPEC 5.8 exists for, and the one the reason codes cannot reach.

    Nothing drained, nothing applied, nothing closed — all_rejected is false —
    and the screen is still SEALED, because the section is sealed whether or
    not a player happened to submit a move this sweep.
    """
    plan = close_plan(section=SECTION_SEALED)
    assert plan["post_push"] == [], "this fixture must drain nothing"
    result = run_work_step(tmp_path, plan)
    assert result.returncode == 0, result
    assert result.outputs["closes"] == "false"
    assert result.outputs["all_rejected"] == "false"
    assert result.outputs["state_screen"] == "SEALED", result


def test_a_quiet_capped_run_still_reports_the_log_full_screen(tmp_path):
    """The symmetry that makes this an enum rather than a `sealed` boolean: a
    section at its cap with an empty queue was equally invisible."""
    result = run_work_step(tmp_path, close_plan(section=SECTION_CAPPED))
    assert result.returncode == 0, result
    assert result.outputs["all_rejected"] == "false"
    assert result.outputs["state_screen"] == "LOG_FULL", result


def test_a_run_that_applied_moves_into_the_cap_still_reports_log_full(tmp_path):
    """The decisive test that the screen is not gated on all_rejected.

    A batch whose applied moves pushed the section to the SPEC 6 cap reports
    `capped` (SPEC 5.8 clause 3 — the state describes the section the NEXT move
    lands in), yet all_rejected is false because everything applied.
    """
    plan = close_plan((1, "applied"), section=SECTION_CAPPED)
    result = run_work_step(tmp_path, plan, f"{ledger_line(TS, 'p', 'fire', 1, 1)}\n")
    assert result.returncode == 0, result
    assert result.outputs["all_rejected"] == "false"
    assert result.outputs["state_screen"] == "LOG_FULL", result


def test_an_all_rejected_batch_on_an_open_section_selects_no_screen(tmp_path):
    """The other direction: all_rejected true, no screen.

    A batch declined only for grammar or cooldown is ordinary operation on a
    live game with an accurate frame on display. This asymmetry is why
    all_rejected and state_screen are two outputs rather than one.
    """
    result = run_work_step(tmp_path, close_plan((1, "grammar"), (2, "cooldown"),
                                                section=SECTION_OPEN))
    assert result.returncode == 0, result
    assert result.outputs["all_rejected"] == "true"
    assert result.outputs["state_screen"] == ""


def test_the_screen_does_not_change_when_the_reason_codes_do(tmp_path):
    """The lookup reads `.section.state` and nothing else.

    Same section state, three different code mixes: one screen. Under the old
    reason-code derivation two of these produce a different answer.
    """
    screens = set()
    for index, codes in enumerate([
        [(1, "grammar")], [(1, "sealed")], [(1, "section-cap"), (2, "duplicate")],
    ]):
        result = run_work_step(tmp_path / f"case{index}",
                               close_plan(*codes, section=SECTION_CAPPED))
        assert result.returncode == 0, result
        screens.add(result.outputs["state_screen"])
    assert screens == {"LOG_FULL"}, screens


def test_a_section_state_outside_the_mapping_enum_fails_the_step(tmp_path):
    """SPEC 5.8: the consumer maps a value it was handed and hard-fails on an
    unmapped one, rather than deciding for itself what the value means."""
    result = run_work_step(tmp_path, close_plan((1, "grammar"), section="banana"))
    assert result.returncode != 0, result
    assert "::error::" in result.log, result.log
    assert "banana" in result.log, result.log


def test_a_missing_section_member_fails_the_step(tmp_path):
    """SPEC 5.8 clause 1 makes the field unconditional on every exit-0 drain, so
    its absence is a defect in the drain — the same class as a missing `reason`,
    and it must be refused for the same reason: silently defaulting to "no
    screen" would leave a sealed game showing a stale live frame."""
    plan = close_plan((1, "grammar"), section=NO_SECTION_FIELD)
    assert "section" not in plan, plan
    result = run_work_step(tmp_path, plan)
    assert result.returncode != 0, result
    assert "::error::" in result.log, result.log


def test_a_rejected_section_state_produces_no_step_output(tmp_path):
    """A defect in the drain must not produce a verdict about the game."""
    for index, plan in enumerate((close_plan((1, "grammar"), section="banana"),
                                  close_plan((1, "grammar"),
                                             section=NO_SECTION_FIELD))):
        result = run_work_step(tmp_path / f"case{index}", plan)
        assert result.outputs == {}, result


def test_the_section_state_enum_is_read_from_the_mapping(tmp_path):
    """Point the step at a mapping missing one state and that state must be
    refused. If the enum were retyped into YAML this passes anyway."""
    narrowed = load_mapping()
    narrowed["section_states"] = [s for s in SECTION_STATES if s != SECTION_CAPPED]
    mapping_path = write_mapping(tmp_path, narrowed, name="narrowed.json")
    result = run_work_step(tmp_path / "step",
                           close_plan((1, "grammar"), section=SECTION_CAPPED),
                           mapping=mapping_path)
    assert result.returncode != 0, result


def test_the_section_state_is_matched_byte_exactly(tmp_path):
    """`SEALED` is not `sealed`: the enum is a protocol, not prose."""
    result = run_work_step(tmp_path, close_plan((1, "grammar"), section="SEALED"))
    assert result.returncode != 0, result


# --- The grammar-only asymmetry (why there are four outputs) ----------------
def test_a_grammar_only_batch_is_all_rejected_with_no_state_screen(drive):
    """Genuinely all-rejected — nothing was appended — but the game is live and
    the displayed frame is accurate, so no SPEC 11 guidance screen applies.
    Reporting a swap here would be false."""
    _, _, result = drive("grammar-only")
    assert result.outputs["all_rejected"] == "true"
    assert result.outputs["state_screen"] == ""


def test_the_scenario_table_covers_both_halves_of_the_asymmetry():
    """Coverage guard over the table above, so neither half can be dropped.

    all_rejected and state_screen must each be observed true-with-no-screen and
    screen-with-no-all_rejected; a table missing either would let the two
    signals be collapsed without any test noticing.
    """
    rejected_no_screen, screen_not_rejected = set(), set()
    for scenario_id, case in SCENARIOS.items():
        screen = SCREEN_FOR_SECTION_STATE[case["section"]]
        if case["expect"]["all_rejected"] == "true" and not screen:
            rejected_no_screen.add(scenario_id)
        if case["expect"]["all_rejected"] == "false" and screen:
            screen_not_rejected.add(scenario_id)
    assert rejected_no_screen, "no all-rejected scenario without a state screen"
    assert screen_not_rejected, "no state-screen scenario that is not all-rejected"


# --- `duplicate` is excluded from "drained" ---------------------------------
def test_a_close_only_duplicate_sweep_is_not_reported_as_a_rejected_batch(drive):
    """An already-ledgered issue never consumed the cap and was never a
    candidate this run, so counting it would make pure cleanup look rejected."""
    _, _, result = drive("duplicate-only")
    assert result.outputs["all_rejected"] == "false"
    assert result.outputs["closes"] == "true", "the closes must still be executed"


@pytest.mark.parametrize(
    "scenario_id", ["grammar-only", "sealed", "section-cap", "ordinary-batch"]
)
def test_adding_duplicates_to_a_batch_changes_none_of_the_four_outputs(
    tmp_path, scenario_id
):
    """The exclusion stated as a property, not as one instance of it."""
    case = SCENARIOS[scenario_id]
    _, _, baseline = run_drain_then_work_step(
        tmp_path / "baseline", case["issues"], case["ledger"]
    )
    padded_ledger = case["ledger"].rstrip("\n") + "\n" + "\n".join(
        ledger_line(TS, "old", "fire", 1, number) for number in (901, 902, 903)
    ) + "\n"
    padded_issues = list(case["issues"]) + [
        make_issue(number, "doom: fire", TS) for number in (901, 902, 903)
    ]
    actions, _, padded = run_drain_then_work_step(
        tmp_path / "padded", padded_issues, padded_ledger
    )
    assert reason_codes_of(actions).count("duplicate") == 3, (
        "the padding must actually arrive as duplicates for this to test anything"
    )
    assert padded.returncode == baseline.returncode == 0
    assert padded.outputs == baseline.outputs, (baseline, padded)


# --- A ledger/applied disagreement fails pre-push ---------------------------
MISMATCH_PLANS = {
    "more-applied-than-lines": (close_plan((1, "applied"), (2, "applied")), ""),
    "more-lines-than-applied": (
        close_plan((1, "applied")),
        f"{ledger_line(TS, 'p', 'fire', 1, 1)}\n{ledger_line(TS, 'p', 'back', 1, 2)}\n",
    ),
    "lines-with-no-applied-close": (
        close_plan((1, "grammar")),
        f"{ledger_line(TS, 'p', 'fire', 1, 1)}\n",
    ),
}


@pytest.mark.parametrize("case_id", list(MISMATCH_PLANS), ids=list(MISMATCH_PLANS))
def test_a_ledger_line_and_applied_close_disagreement_fails_the_step(tmp_path, case_id):
    plan, moves_text = MISMATCH_PLANS[case_id]
    result = run_work_step(tmp_path, plan, moves_text)
    assert result.returncode != 0, result
    assert "::error::" in result.log and "disagree" in result.log, result.log


@pytest.mark.parametrize("case_id", list(MISMATCH_PLANS), ids=list(MISMATCH_PLANS))
def test_the_mismatch_guard_writes_no_step_output(tmp_path, case_id):
    """Pre-push means nothing downstream can act: the closes, the swap and the
    push are all gated on outputs this step never gets to write."""
    plan, moves_text = MISMATCH_PLANS[case_id]
    result = run_work_step(tmp_path, plan, moves_text)
    assert result.outputs == {}, result


def test_the_close_step_is_gated_on_the_work_steps_closes_output():
    """The other half of "pre-push, not after issues are closed".

    The step above proves a mismatch writes no `closes`; this proves the close
    step consumes exactly that output, so together they mean a mismatch cannot
    reach the GitHub side effects.
    """
    condition = workflow_step_field("Close issues and post receipts", "if")
    assert "steps.work.outputs.closes == 'true'" in condition, condition


def test_an_unterminated_ledger_batch_is_refused_as_a_disagreement(tmp_path):
    """`wc -l` counts newlines, so a batch missing its final LF undercounts.

    drain.py always terminates the file, so this is unreachable today; the test
    pins that the two sides of the guard agree on what a "line" is rather than
    leaving it to coincidence.
    """
    result = run_work_step(tmp_path, close_plan((1, "applied")),
                           ledger_line(TS, "p", "fire", 1, 1))
    assert result.returncode != 0, result
    assert "disagree" in result.log, result.log


# --- The SPEC 5.7 closed-enum guard -----------------------------------------
def test_a_reason_code_outside_the_enum_fails_the_step(tmp_path):
    result = run_work_step(tmp_path, close_plan((1, "banned")))
    assert result.returncode != 0, result
    assert "SPEC 5.7 closed enum" in result.log, result.log
    assert '"banned"' in result.log, result.log


def test_a_post_push_entry_with_no_reason_field_fails_the_step(tmp_path):
    """The near-miss that motivates `tojson`.

    jq's `join` renders a missing field as the empty string, so a `-n` test on
    the joined list saw nothing and waved the defect straight through the guard
    meant to catch it. `tojson` renders it as the literal `null`.
    """
    plan = close_plan((1, NO_REASON_FIELD))
    assert "reason" not in plan["post_push"][0], (
        "the fixture must actually omit the key, not set it to null"
    )
    result = run_work_step(tmp_path, plan)
    assert result.returncode != 0, result
    assert "SPEC 5.7 closed enum" in result.log, result.log
    assert "null" in result.log, (
        "a missing code must be REPORTED, not rendered as an empty string: "
        f"{result.log}"
    )


def test_an_explicitly_null_reason_fails_the_step(tmp_path):
    """The sibling of the missing key: `join` flattens both to "" identically."""
    plan = close_plan((1, None))
    assert plan["post_push"][0]["reason"] is None
    result = run_work_step(tmp_path, plan)
    assert result.returncode != 0, result
    assert "null" in result.log, result.log


def test_a_reason_that_is_not_a_string_fails_the_step(tmp_path):
    result = run_work_step(tmp_path, close_plan((1, 7)))
    assert result.returncode != 0, result
    assert "SPEC 5.7 closed enum" in result.log, result.log


def test_one_valid_code_does_not_excuse_an_invalid_one_in_the_same_plan(tmp_path):
    result = run_work_step(tmp_path, close_plan((1, "sealed"), (2, "banned")))
    assert result.returncode != 0, result
    assert '"banned"' in result.log, result.log


def test_every_distinct_unknown_code_is_reported_once(tmp_path):
    plan = close_plan((1, "banned"), (2, "banned"), (3, "invented"))
    result = run_work_step(tmp_path, plan)
    assert result.returncode != 0, result
    errors = [line for line in result.log.splitlines() if "::error::" in line]
    assert len(errors) == 1, errors
    assert errors[0].count('"banned"') == 1, errors[0]
    assert '"invented"' in errors[0], errors[0]


def test_an_unknown_code_is_refused_rather_than_counted_as_a_rejection(tmp_path):
    """The reason the guard fails loudly instead of falling through.

    Under the arithmetic below it an unrecognized code counts as drained and
    not applied — silently producing all_rejected on a batch nobody understands.
    """
    result = run_work_step(tmp_path, close_plan((1, "banned")))
    assert result.returncode != 0
    assert result.outputs == {}, (
        "a defect in the drain must not produce a verdict about the game: "
        f"{result.outputs}"
    )


def test_all_six_mapping_reason_codes_pass_the_guard(tmp_path):
    """No false positives: the guard admits exactly the enum it is given."""
    plan = close_plan(*[(index + 1, code) for index, code in enumerate(REASON_CODES)])
    applied = REASON_CODES.count("applied")
    moves_text = "".join(
        f"{ledger_line(TS, 'p', 'fire', 1, 500 + i)}\n" for i in range(applied)
    )
    result = run_work_step(tmp_path, plan, moves_text)
    assert result.returncode == 0, result
    assert set(result.outputs) == WORK_STEP_OUTPUTS


def test_the_reason_code_enum_is_read_from_the_mapping(tmp_path):
    """Point it at a mapping missing one code and that code must now be refused.

    If the enum were retyped into YAML this passes anyway — the drift SPEC 5.7
    and SPEC 0.5 both forbid.
    """
    narrowed = load_mapping()
    narrowed["reason_codes"] = [c for c in REASON_CODES if c != "sealed"]
    mapping_path = write_mapping(tmp_path, narrowed, name="narrowed.json")
    result = run_work_step(tmp_path / "step", close_plan((1, "sealed")),
                           mapping=mapping_path)
    assert result.returncode != 0, result
    assert '"sealed"' in result.log, result.log


def test_a_code_the_drain_does_not_emit_but_the_mapping_lists_is_admitted(tmp_path):
    """The mapping is the authority in both directions, not a subset check."""
    widened = load_mapping()
    widened["reason_codes"] = REASON_CODES + ["future-code"]
    mapping_path = write_mapping(tmp_path, widened, name="widened.json")
    result = run_work_step(tmp_path / "step", close_plan((1, "future-code")),
                           mapping=mapping_path)
    assert result.returncode == 0, result
    assert result.outputs["all_rejected"] == "true"


def test_the_reason_guard_matches_codes_byte_exactly(tmp_path):
    """`SEALED` is not `sealed`: the enum is a protocol, not prose."""
    result = run_work_step(tmp_path, close_plan((1, "SEALED")))
    assert result.returncode != 0, result
    assert '"SEALED"' in result.log, result.log


def test_rewording_a_player_visible_message_does_not_change_the_verdict(tmp_path):
    """SPEC 5.7's consumer rule: messages are written for humans and may be
    reworded; the codes may not."""
    plan = close_plan((1, "sealed"), section=SECTION_SEALED)
    plan["post_push"][0]["message"] = "totally different guidance text"
    result = run_work_step(tmp_path, plan)
    assert result.returncode == 0, result
    assert result.outputs["state_screen"] == "SEALED", result


# --- Producer / consumer: the screens the swap step can render --------------
def swap_step_case_labels():
    """The literal labels of the swap step's authoritative `case` arms."""
    labels = []
    for line in workflow_step_run(STATE_SWAP_STEP).splitlines():
        stripped = line.strip()
        if ")" in stripped and stripped.endswith(";;"):
            label = stripped.split(")", 1)[0].strip()
            if label != "*":
                labels.append(label)
    return labels


def test_the_swap_step_maps_exactly_the_screens_the_lookup_can_produce():
    """Binds producer to consumer in both directions.

    A screen the work step can emit but the swap step does not map hits the
    `*)` arm and fails the run; an arm for a screen nothing can produce is dead
    code that no test would ever reach.
    """
    producible = {screen for screen in SCREEN_FOR_SECTION_STATE.values() if screen}
    assert set(swap_step_case_labels()) == producible, (
        f"swap step maps {sorted(swap_step_case_labels())}; the SPEC 5.8 lookup "
        f"produces {sorted(producible)}"
    )


def test_the_swap_step_refuses_a_state_screen_it_does_not_map(tmp_path):
    """The `if:` prefilter folds case (Actions expression comparison is
    case-insensitive), so the `case` statement is the authoritative match."""
    result = run_workflow_step(
        workflow_step_run(STATE_SWAP_STEP),
        runner_temp=tmp_path,
        env={"STATE_SCREEN": "sealed", "CONTROLS_ENABLED": "false",
             "SCREEN_SEALED": "game/assets/screens/sealed.png",
             "SCREEN_LOG_FULL": "game/assets/screens/log-full.png",
             "GITHUB_RUN_ID": "0", "GITHUB_REF_NAME": "test"},
    )
    assert result.returncode != 0, result
    assert "unknown state screen" in result.log, result.log


def test_the_swap_gate_does_not_require_an_all_rejected_batch():
    """SPEC 5.8's whole purpose is the quiet run.

    A sealed section with an empty queue has all_rejected false and a SEALED
    screen; gating the swap on all_rejected would leave exactly the visitor the
    field exists for looking at a stale live frame.
    """
    condition = workflow_step_field(STATE_SWAP_STEP, "if")
    assert "all_rejected" not in condition, condition
    assert "steps.work.outputs.state_screen" in condition, condition


# --- moves / closes ---------------------------------------------------------
def test_moves_is_false_for_a_zero_byte_ledger_batch(tmp_path):
    result = run_work_step(tmp_path, close_plan((1, "grammar")), "")
    assert result.outputs["moves"] == "false"


def test_closes_is_false_only_when_the_plan_has_no_post_push_entry(tmp_path):
    result = run_work_step(tmp_path, close_plan(), "")
    assert result.returncode == 0, result
    assert result.outputs["closes"] == "false"
    assert result.outputs["all_rejected"] == "false"
