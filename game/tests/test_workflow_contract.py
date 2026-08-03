"""
@spec-handoff
@interface .github/workflows/doom.yml — file-wide invariants, not one step.
    No implementation target: this is a regression guard over a workflow that
    already exists, in the shape test_spec_mapping_consistency.py uses for
    SPEC/mapping drift.
@behavior
    - SPEC 0.5: a gate has exactly one implementation site. Where Actions
      genuinely cannot read the owning source (an `if:` expression cannot read
      a file), the copy is GENERATED-AND-GUARDED, never retyped: every
      `fromJSON('[...]')` title array in the workflow must equal mapping
      canonical_titles exactly, order included
    - Every `run:` body takes its values from env, never from `${{ }}` — the
      workflow's own stated invariant, and the Actions script-injection rule
    - Step `run:` bodies are extractable verbatim, which is what lets the rest
      of the workflow suite execute the shipped shell instead of a transcript
@edge-cases
    - An extraction that matches nothing FAILS loudly; a guard that silently
      finds no arrays to compare would pass vacuously forever
    - The `if:` prefilter folds case (Actions comparison is case-insensitive),
      so this guard is about DRIFT of the copy, not about authority: the
      parser stays the authoritative match
@see game/SPEC.md 0.5 and 3; game/mapping/v1.json canonical_titles;
    .yui-soul/knowledge/gotchas/gh.md
"""

import json
import re

import pytest
from conftest import (
    CANONICAL_TITLE_COUNT,
    WORK_STEP,
    WORKFLOW_PATH,
    load_mapping,
    workflow_run_blocks,
    workflow_step_run,
)

FROM_JSON_ARRAY = re.compile(r"fromJSON\('(\[.*?\])'\)", re.S)


def workflow_text():
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def from_json_title_arrays():
    """Every inlined JSON array of `doom: ` titles in the workflow."""
    found = []
    for index, raw in enumerate(FROM_JSON_ARRAY.findall(workflow_text())):
        parsed = json.loads(raw)
        if all(isinstance(item, str) and item.startswith("doom: ") for item in parsed):
            found.append((index, parsed))
    return found


# --- SPEC 0.5: the one duplication site Actions cannot avoid ----------------
def test_the_workflow_inlines_at_least_one_canonical_title_array():
    """A guard that finds nothing to compare passes vacuously forever.

    If the arrays are ever removed (an Actions feature that can read a file, a
    different prefilter), this test is the notice that the guard below has
    stopped guarding anything and should be deleted rather than left green.
    """
    assert from_json_title_arrays(), (
        "no `fromJSON('[...]')` title array found in doom.yml — either the "
        "prefilter changed shape or this guard's pattern has drifted"
    )


def test_every_inlined_title_array_equals_the_mapping_canonical_titles():
    """SPEC 0.5 applied to the last open duplication site in the repo.

    An Actions `if:` expression cannot read a file, so the 56 literals must
    exist a second time in YAML. That makes the copy generated-and-guarded, not
    a licence to retype: nothing else in the repo notices when it drifts. Harm
    is bounded — the prefilter is cost control and the parser is authoritative,
    so drift costs a delayed move rather than a wrong one — which is why this
    is a guard and not a redesign.
    """
    canonical = load_mapping()["canonical_titles"]
    for index, titles in from_json_title_arrays():
        assert titles == canonical, (
            f"DRIFT [canonical_titles]: doom.yml fromJSON array #{index} "
            f"disagrees with game/mapping/v1.json. Missing from the workflow: "
            f"{sorted(set(canonical) - set(titles))}; not in the mapping: "
            f"{sorted(set(titles) - set(canonical))}; order equal: "
            f"{sorted(titles) == sorted(canonical) and titles != canonical}"
        )


def test_every_inlined_title_array_is_the_full_gate_set():
    """SPEC 3 fixes the size at 56. A short array is a hole in the prefilter
    that set-equality against a drifted mapping could not catch on its own."""
    for index, titles in from_json_title_arrays():
        assert len(titles) == CANONICAL_TITLE_COUNT == 56, (
            f"DRIFT [canonical_titles]: doom.yml array #{index} has "
            f"{len(titles)} entries, SPEC 3 fixes the gate set at 56"
        )
        assert len(set(titles)) == len(titles), (
            f"doom.yml array #{index} repeats a title"
        )


def test_no_inlined_array_carries_a_title_the_mapping_does_not_declare():
    """Stated as its own assertion because this is the direction that admits a
    title the parser will then decline — a wasted run, not a missed move."""
    canonical = set(load_mapping()["canonical_titles"])
    for index, titles in from_json_title_arrays():
        extra = sorted(set(titles) - canonical)
        assert not extra, (
            f"DRIFT [canonical_titles]: doom.yml array #{index} admits titles "
            f"the mapping does not declare: {extra}"
        )


# --- The env-only rule that makes verbatim extraction sound -----------------
def test_no_run_block_body_contains_an_actions_expression():
    """doom.yml's own stated invariant: every value reaches a script through env.

    Two things at once. It is the Actions script-injection rule — `${{ }}` is
    substituted before the shell parses the line — and it is what lets this
    suite execute the shipped bodies verbatim, with no substitution step that
    could itself drift from what the runner does.
    """
    offenders = [
        (name, line.strip())
        for name, script in workflow_run_blocks()
        for line in script.splitlines()
        if "${{" in line
    ]
    assert offenders == [], (
        "run: bodies must take values from env, never from an expression: "
        f"{offenders}"
    )


def test_the_workflow_has_run_blocks_to_check():
    """The vacuity guard for the test above."""
    assert len(workflow_run_blocks()) > 5, workflow_run_blocks()


# --- The extraction harness itself ------------------------------------------
def test_the_extracted_step_matches_what_a_yaml_parser_reads():
    """The extractor must return the shipped bytes, not a plausible rendering.

    Skips where PyYAML is absent (CI installs pytest only, so this cross-check
    does not run there — see the report). The extraction is still exercised by
    every behavioural workflow test, none of which can pass if the wrong script
    ran; this pins the stronger claim of byte equality.
    """
    yaml = pytest.importorskip(
        "yaml",
        reason="SKIP[yaml-crosscheck]: PyYAML absent; the extractor is still "
               "exercised by every behavioural test in the workflow suite",
    )
    document = yaml.safe_load(workflow_text())
    parsed = {
        step["name"]: step["run"]
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step and "name" in step
    }
    assert parsed, "no named run: steps parsed out of doom.yml"
    for name, script in parsed.items():
        assert workflow_step_run(name) == script, name


def test_extracting_an_absent_step_fails_rather_than_returning_something():
    """A silently wrong extraction would run a DIFFERENT script than the one
    under test and could still go green."""
    with pytest.raises(AssertionError, match="no step named"):
        workflow_step_run("This step does not exist")


def test_the_extracted_work_step_is_a_shell_script_not_a_yaml_fragment():
    script = workflow_step_run(WORK_STEP)
    assert script.startswith("set -euo pipefail\n"), script[:80]
    assert not any(line.startswith("- name:") for line in script.splitlines())
    assert script.endswith("\n")
