"""
@spec-handoff
@interface Failure-path write contract (SPEC section 10, RFC normative table)
    projected onto the standalone scripts' composition. The harness in this file
    models the workflow: drain.py -> append moves -> [encode result as a byte
    file] -> budget.py ladder -> rewrite_readme.py, with pushes modeled as
    copies into a remote/ dir and closes taken from the drain actions file's
    post_push phase. Game state = ledger + GIF (remote); display state = the
    README marker block.
@behavior
    - Success row: ledger and README(LIVE) advance together; the GIF push
      precedes the state push; closes execute only after both
    - Pre-push failure (budget hard-fail): remote game state untouched; README
      best-effort swap -> UNAVAILABLE, itself passing marker validation
    - Marker-validation failure: rewriter exits 6 leaving the README
      byte-untouched; the swap is suppressed; remote untouched; no closes
    - Game-state push failure: the GIF may have landed (tolerated per the
      amended row); the ledger must not; closes never execute
    - Post-push failure (close step): the LIVE README is never rewritten;
      a re-run treats ledgered issues as close-duplicate (no re-append)
    - Runner loss / early exit: a script failing usage (exit 2) leaves every
      pre-existing output file byte-untouched (atomic temp+rename writes)
@edge-cases
    - The UNAVAILABLE swap on a pre-push failure is display-only: it must not
      touch the ledger even in the local workspace copy that would be pushed
@see game/SPEC.md section 10; RFC 001 "Failure-path write contract"; must_have 6
"""

import shutil

import pytest

from conftest import (
    BUDGET_CEILING_BYTES,
    MAPPING_PATH,
    inside_block_bytes,
    ledger_line,
    load_actions,
    make_issue,
    make_readme_bytes,
    make_section_text,
    outside_parts_bytes,
    run_budget,
    run_drain,
    TEST_REPOSITORY,
    run_rewriter,
    run_script,
    sparse_file,
)

TS = "2026-07-30T14:02:11Z"
GIF_URL = "https://raw.githubusercontent.com/nikitastetskiy/nikitastetskiy/output/doom.gif?run=777"


class Workspace:
    """A miniature checkout + remote pair driving the real scripts."""

    def __init__(self, root, readme_bytes=None, ledger_text=None):
        self.root = root
        self.remote = root / "remote"
        self.remote.mkdir()
        self.readme = root / "README.md"
        self.readme.write_bytes(readme_bytes if readme_bytes is not None else make_readme_bytes())
        self.ledger = root / "log.txt"
        self.ledger.write_text(
            ledger_text if ledger_text is not None else make_section_text([], n=1),
            encoding="ascii",
        )
        # remote starts in sync
        shutil.copy(self.ledger, self.remote / "log.txt")
        self.events = []
        self.closed = []

    def remote_ledger_bytes(self):
        return (self.remote / "log.txt").read_bytes()


def compose_run(ws, issues_dir, issues, *, gif_size, fail_state_push=False, fail_closes=False):
    """Drive drain -> budget ladder -> rewrite -> pushes -> closes, honoring the
    write contract's ordering. Returns the terminal outcome string."""
    proc, moves_path, actions_path = run_drain(
        issues_dir, issues, ws.ledger.read_text(encoding="ascii")
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    actions = load_actions(actions_path)

    # workspace ledger append (not yet "pushed")
    appended = ws.ledger.read_text(encoding="ascii") + moves_path.read_text(encoding="ascii")
    ws.ledger.write_text(appended, encoding="ascii")

    # encode result modeled as a byte file; budget ladder decides
    gif = sparse_file(issues_dir, "frame.gif", gif_size)
    rung_result = None
    for rung in ("L0", "L1", "L2"):
        budget = run_budget(rung, file=gif)
        assert budget.returncode in (0, 10, 11), budget.stderr
        if budget.returncode == 0:
            rung_result = rung
            break
        if budget.returncode == 11:
            # pre-push failure: display-only best-effort swap -> UNAVAILABLE
            swap = run_rewriter(ws.readme, state="UNAVAILABLE",
                                image_url="https://example.com/unavailable.png")
            ws.events.append(("swap", swap.returncode))
            return "pre-push-failure"

    # marker-validated LIVE rewrite before any push
    # SPEC 9.1: the control-link target is supplied at render time. This
    # simulation renders the control table, so it must name one — the same
    # obligation doom.yml has, from GITHUB_REPOSITORY.
    rewrite = run_rewriter(ws.readme, state="LIVE", image_url=GIF_URL,
                           controls_enabled=True, repository=TEST_REPOSITORY)
    if rewrite.returncode == 6:
        return "marker-validation-failure"  # swap suppressed: nothing else runs
    assert rewrite.returncode == 0, (rewrite.stdout, rewrite.stderr)

    # push GIF to the output branch FIRST
    shutil.copy(gif, ws.remote / "doom.gif")
    ws.events.append(("push-gif", rung_result))

    # then the game-state push (ledger + README)
    if fail_state_push:
        swap = run_rewriter(ws.readme, state="UNAVAILABLE",
                            image_url="https://example.com/unavailable.png")
        ws.events.append(("swap", swap.returncode))
        return "game-state-push-failure"
    shutil.copy(ws.ledger, ws.remote / "log.txt")
    shutil.copy(ws.readme, ws.remote / "README.md")
    ws.events.append(("push-state", None))

    # closes strictly after successful pushes
    if fail_closes:
        return "post-push-failure"
    for entry in actions["post_push"]:
        ws.closed.append(entry["issue"])
        ws.events.append(("close", entry["issue"]))
    return "success"


# --- Row 1: Success -----------------------------------------------------------

def test_success_row_advances_ledger_and_live_readme_with_closes_last(tmp_path):
    ws = Workspace(tmp_path)
    issues = [make_issue(17, "doom: forward x5", TS, login="nikitastetskiy")]
    outcome = compose_run(ws, tmp_path, issues, gif_size=150_000)
    assert outcome == "success"
    assert ledger_line(TS, "nikitastetskiy", "forward", 5, 17).encode() in ws.remote_ledger_bytes()
    remote_readme = (ws.remote / "README.md").read_bytes()
    assert b"DOOM (LIVE)" in inside_block_bytes(remote_readme)
    assert GIF_URL.encode() in inside_block_bytes(remote_readme)
    kinds = [kind for kind, _ in ws.events]
    assert kinds == ["push-gif", "push-state", "close"]
    assert ws.closed == [17]


# --- Row 2: Pre-push failure (budget hard-fail) -------------------------------

def test_pre_push_failure_leaves_game_state_untouched_and_swaps_unavailable(tmp_path):
    ws = Workspace(tmp_path)
    before_remote = ws.remote_ledger_bytes()
    issues = [make_issue(21, "doom: fire", TS, login="player")]
    outcome = compose_run(ws, tmp_path, issues, gif_size=BUDGET_CEILING_BYTES + 1)
    assert outcome == "pre-push-failure"
    assert ws.remote_ledger_bytes() == before_remote, "ledger never lands on a failed run"
    assert not (ws.remote / "doom.gif").exists(), "no GIF publish on budget hard-fail"
    assert ws.closed == [], "issues stay open on a pre-push failure"
    assert ("swap", 0) in ws.events, "the display-only swap itself passed marker validation"
    assert b"DOOM (UNAVAILABLE)" in inside_block_bytes(ws.readme.read_bytes())


# --- Row 3: Marker-validation failure -----------------------------------------

def test_marker_failure_suppresses_the_swap_and_touches_nothing(tmp_path):
    corrupted = make_readme_bytes() + b"\nquoted: <!-- DOOM:START -->\n"
    ws = Workspace(tmp_path, readme_bytes=corrupted)
    before_remote = ws.remote_ledger_bytes()
    before_readme = ws.readme.read_bytes()
    issues = [make_issue(22, "doom: back", TS, login="player")]
    outcome = compose_run(ws, tmp_path, issues, gif_size=100_000)
    assert outcome == "marker-validation-failure"
    assert ws.readme.read_bytes() == before_readme, "no write inside invalid markers"
    assert ws.remote_ledger_bytes() == before_remote
    assert not (ws.remote / "doom.gif").exists()
    assert ws.closed == []


# --- Row 4: Game-state push failure -------------------------------------------

def test_state_push_failure_tolerates_landed_gif_but_never_ledger_or_closes(tmp_path):
    ws = Workspace(tmp_path)
    before_remote = ws.remote_ledger_bytes()
    issues = [make_issue(23, "doom: use", TS, login="player")]
    outcome = compose_run(ws, tmp_path, issues, gif_size=100_000, fail_state_push=True)
    assert outcome == "game-state-push-failure"
    assert (ws.remote / "doom.gif").exists(), "amended row: the GIF may have landed"
    assert ws.remote_ledger_bytes() == before_remote, "the ledger must not have landed"
    assert not (ws.remote / "README.md").exists()
    assert ws.closed == [], "closes are gated on the game-state push"
    assert b"DOOM (UNAVAILABLE)" in inside_block_bytes(ws.readme.read_bytes())


# --- Row 5: Post-push failure --------------------------------------------------

def test_post_push_failure_never_rewrites_live_and_next_run_closes_only(tmp_path):
    ws = Workspace(tmp_path)
    issues = [make_issue(24, "doom: turn-left x3", TS, login="player")]
    outcome = compose_run(ws, tmp_path, issues, gif_size=100_000, fail_closes=True)
    assert outcome == "post-push-failure"
    pushed_readme = (ws.remote / "README.md").read_bytes()
    assert b"DOOM (LIVE)" in inside_block_bytes(pushed_readme)
    assert ws.readme.read_bytes() == pushed_readme, "LIVE is never overwritten post-push"
    # next run: same open issue against the now-committed ledger
    rerun_dir = tmp_path / "rerun"
    rerun_dir.mkdir()
    proc, moves_path, actions_path = run_drain(
        rerun_dir, issues, (ws.remote / "log.txt").read_text(encoding="ascii")
    )
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b"", "no double-apply after the crash seam"
    actions = load_actions(actions_path)
    assert [e["action"] for e in actions["post_push"] if e["issue"] == 24] == ["close-duplicate"]


# --- Row 6: Runner loss / early exit -------------------------------------------

@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(
            lambda tmp: run_script(
                "drain.py",
                ["--issues", str(tmp / "absent.json"),
                 "--out-moves", str(tmp / "moves.out"),
                 "--out-actions", str(tmp / "actions.json")],
            ),
            id="drain-usage-error",
        ),
        pytest.param(
            lambda tmp: run_script("rewrite_readme.py", ["--readme", str(tmp / "README.md")]),
            id="rewriter-usage-error",
        ),
        pytest.param(
            lambda tmp: run_script("expand.py", ["--mapping", str(MAPPING_PATH)]),
            id="expander-usage-error",
        ),
        pytest.param(
            lambda tmp: run_script("budget.py", ["--mapping", str(MAPPING_PATH)]),
            id="budget-usage-error",
        ),
    ],
)
def test_early_exit_leaves_preexisting_files_byte_untouched(tmp_path, invoke):
    readme = tmp_path / "README.md"
    readme.write_bytes(make_readme_bytes())
    moves = tmp_path / "moves.out"
    moves.write_bytes(b"sentinel-moves")
    actions = tmp_path / "actions.json"
    actions.write_bytes(b"sentinel-actions")
    proc = invoke(tmp_path)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert readme.read_bytes() == make_readme_bytes()
    assert moves.read_bytes() == b"sentinel-moves"
    assert actions.read_bytes() == b"sentinel-actions"


def test_display_only_swap_does_not_touch_the_workspace_ledger(tmp_path):
    """Row 2 fine print: the UNAVAILABLE swap is display-only — the ledger file
    the swap-run would have pushed is exactly the pre-run committed ledger plus
    nothing that got published."""
    ws = Workspace(tmp_path)
    committed = ws.remote_ledger_bytes()
    issues = [make_issue(25, "doom: fire", TS, login="player")]
    compose_run(ws, tmp_path, issues, gif_size=BUDGET_CEILING_BYTES + 1)
    outside_before = outside_parts_bytes(make_readme_bytes())
    outside_after = outside_parts_bytes(ws.readme.read_bytes())
    assert outside_after == outside_before, "swap writes only inside the markers"
    assert ws.remote_ledger_bytes() == committed
