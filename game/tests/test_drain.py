"""
@spec-handoff
@interface drain.py --issues FILE --ledger FILE --mapping PATH --toolchain PATH
    --out-moves PATH --out-actions PATH; issues FILE = JSON array of {number:int, title:str,
    created_at:"YYYY-MM-DDTHH:MM:SSZ", user:{login:str}} (GitHub REST subset —
    unit inputs are files, never live API; no network, no wall clock); exit 0
    ok / 2 usage (bad or missing arguments, nonexistent input file) / 5 corrupt
    content (unparseable ledger or issues JSON)
@behavior
    - Only titles byte-prefixed "doom: " are considered; every other issue gets
      NO action of any kind (Nik's normal issues are untouchable)
    - Ascending issue-number order (RFC D14 total order); numbers already in the
      committed ledger -> action "close-duplicate", never re-appended and not
      counted against the cap; then up to 20 (mapping knob) unledgered issues
      are taken, the rest left untouched for the next run; every taken title is
      re-validated through game/scripts/parse_title.py (TOCTOU); grammar rejects
      -> "close-reject" carrying the parser's fixed message, no title echo
    - new-game: rejected with a fixed cooldown message if its created_at is
      < 30 min (mapping knob) after the last applied reset (last new-game ledger
      entry, updated in-run as resets are accepted); at section cap (current
      section >= 120,000 expanded frames) valid non-new-game moves are rejected
      with exactly "log full — start a new game"; an accepted new-game opens a
      fresh empty section for the rest of the run
    - out-moves: canonical SPEC 5.3 ledger lines (issue created_at, sanitized
      handle = strip chars outside [a-zA-Z0-9-], truncate 39, empty -> "player",
      token id, count, #number), ascending, one per line, trailing LF; zero
      moves -> zero-byte file. out-actions: JSON {"mapping_version": 1, "moves":
      [{"issue","token","count"}...], "post_push": [{"issue","action":
      close-applied|close-duplicate|close-reject, "message": str|null,
      "reason": <code>}...]} — ALL closes live under post_push (executed
      strictly after successful pushes, RFC D14 step 7); byte-deterministic for
      identical inputs
    - AMENDMENT (Kou is changing drain.py's emitted plan, not only adding a new
      script): every post_push entry gains a machine-readable "reason" code so
      .github/workflows/doom.yml can branch WITHOUT re-deriving any normative
      constant in YAML. Exactly one of:
        applied     -> close-applied
        duplicate   -> close-duplicate (already in the committed ledger)
        grammar     -> close-reject from the parser's whitelist
        cooldown    -> close-reject, `new game` inside the D16 cooldown
        section-cap -> close-reject, active section at the SPEC §6 frame cap
        sealed      -> close-reject, the current section is SEALED (SPEC 5.5)
      "section-cap" is load-bearing: it is the trigger the workflow needs to
      swap in the LOG_FULL state screen (game/assets/screens/log-full.png,
      currently committed with no consumer). The human-facing "message" string
      stays exactly as it is — reason is additive, never a replacement, and the
      two must agree
    - SEALED MODE (SPEC 5.5, ratified in 5e2c68f). NEW REQUIRED ARGUMENT
      --toolchain PATH: sealing is computed at run time by comparing the
      CURRENT section's header against game/toolchain.json
      (engine.commit_sha, engine.build_sha256.value, wad.sha256) and the
      mapping file's mapping_version. Any disagreement seals the section.
      * while sealed, the ONLY admissible move is `doom: new game`; every
        other otherwise-valid move is close-rejected with the verbatim
        message "the arcade is being upgraded — press New game to continue"
        and reason "sealed". Rejecting rather than failing the run is
        REQUIRED: the drain is ascending by issue number, so refusing the
        batch would re-refuse the same low-numbered issue forever (livelock)
      * the `new game` cooldown does NOT apply while sealed (rule 6) — a
        sealed game cannot advance, so the anti-grief purpose is inapplicable
        and a visitor cannot induce a mismatch
      * a run whose drained moves are ALL sealed-rejects is a SUCCESS with an
        empty out-moves file and exit 0 — not a failure (SPEC 5.5 rule 7 / 10)
@edge-cases
    - Per-issue malformed records (missing keys / bad created_at): skipped with
      no action; header insertion after an accepted new-game is the appender's
      job (drain emits ledger lines only)
@see game/SPEC.md sections 4 and 6; RFC D14/D16; game/scripts/parse_title.py
"""

import json

import pytest

from conftest import (
    DRAIN_CAP_ISSUES_PER_RUN,
    LOG_FULL_MESSAGE,
    NEW_GAME_COOLDOWN_MINUTES,
    SEALED_MESSAGE,
    SECTION_CAP_FRAMES,
    ledger_line,
    load_actions,
    load_mapping,
    make_issue,
    make_section_text,
    make_toolchain,
    run_drain,
    run_parser,
    sealed_section_text,
    json_stdout,
)

TS = "2026-07-30T14:02:11Z"
EMPTY_LEDGER = make_section_text([], n=1)

# Machine-readable reason codes on the post_push plan (see the @spec-handoff
# amendment). The workflow branches on these; it must never re-derive a
# normative constant in YAML.
REASON_APPLIED = "applied"
REASON_DUPLICATE = "duplicate"
REASON_GRAMMAR = "grammar"
REASON_COOLDOWN = "cooldown"
REASON_SECTION_CAP = "section-cap"
REASON_SEALED = "sealed"
REASON_CODES = {
    REASON_APPLIED, REASON_DUPLICATE, REASON_GRAMMAR,
    REASON_COOLDOWN, REASON_SECTION_CAP, REASON_SEALED,
}
ACTION_FOR_REASON = {
    REASON_APPLIED: "close-applied",
    REASON_DUPLICATE: "close-duplicate",
    REASON_GRAMMAR: "close-reject",
    REASON_COOLDOWN: "close-reject",
    REASON_SECTION_CAP: "close-reject",
    REASON_SEALED: "close-reject",
}


def post_push_by_issue(actions):
    return {entry["issue"]: entry for entry in actions["post_push"]}


# --- Ascending order and ledger-line emission --------------------------------

def test_accepted_moves_are_emitted_in_ascending_issue_order(tmp_path):
    issues = [
        make_issue(31, "doom: fire", "2026-07-30T14:05:00Z", login="carol"),
        make_issue(17, "doom: forward x5", TS, login="nikitastetskiy"),
        make_issue(23, "doom: use", "2026-07-30T14:03:00Z", login="bob"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert moves_path.read_text(encoding="ascii") == (
        ledger_line(TS, "nikitastetskiy", "forward", 5, 17) + "\n"
        + ledger_line("2026-07-30T14:03:00Z", "bob", "use", 1, 23) + "\n"
        + ledger_line("2026-07-30T14:05:00Z", "carol", "fire", 1, 31) + "\n"
    )
    actions = load_actions(actions_path)
    assert [m["issue"] for m in actions["moves"]] == [17, 23, 31]


def test_order_is_by_issue_number_even_when_timestamps_disagree(tmp_path):
    """RFC D14: issue number is the total order; created_at can tie or invert."""
    issues = [
        make_issue(101, "doom: back", "2026-07-30T14:09:00Z"),
        make_issue(102, "doom: fire", "2026-07-30T14:01:00Z"),
    ]
    proc, moves_path, _ = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert [line.split()[-1] for line in lines] == ["#101", "#102"]


# --- Exactly-once: ledger idempotency keys -----------------------------------

def test_issue_already_in_ledger_is_close_only_and_never_reappended(tmp_path):
    ledger = make_section_text(
        [ledger_line(TS, "nikitastetskiy", "forward", 5, 17)], n=1
    )
    issues = [
        make_issue(17, "doom: forward x5", TS, login="nikitastetskiy"),
        make_issue(18, "doom: fire", "2026-07-30T14:10:00Z", login="dana"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii") == (
        ledger_line("2026-07-30T14:10:00Z", "dana", "fire", 1, 18) + "\n"
    )
    actions = load_actions(actions_path)
    by_issue = post_push_by_issue(actions)
    assert by_issue[17]["action"] == "close-duplicate"
    assert by_issue[17]["message"] is None
    assert by_issue[18]["action"] == "close-applied"
    assert [m["issue"] for m in actions["moves"]] == [18]


def test_ledgered_numbers_from_any_prior_section_are_skipped(tmp_path):
    ledger = (
        make_section_text([
            ledger_line("2026-07-30T13:00:00Z", "alice", "fire", 1, 5),
            ledger_line("2026-07-30T13:30:00Z", "alice", "new-game", 1, 6),
        ], n=1)
        + make_section_text([], n=2)
    )
    issues = [make_issue(5, "doom: fire", "2026-07-30T13:00:00Z", login="alice")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    assert post_push_by_issue(load_actions(actions_path))[5]["action"] == "close-duplicate"


def test_drain_output_is_reentrant_after_its_own_append(tmp_path):
    """Crash-between-push-and-close seam: a second run over the updated ledger
    only closes, never double-applies (consumed == in committed ledger)."""
    issues = [make_issue(40, "doom: turn-left x3", TS, login="eve")]
    proc, moves_path, _ = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    appended = EMPTY_LEDGER + moves_path.read_text(encoding="ascii")
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    proc2, moves2, actions2 = run_drain(tmp2, issues, appended)
    assert proc2.returncode == 0
    assert moves2.read_bytes() == b""
    assert post_push_by_issue(load_actions(actions2))[40]["action"] == "close-duplicate"


# --- Per-run drain cap --------------------------------------------------------

def test_per_run_cap_takes_the_20_lowest_numbers_and_leaves_the_rest(tmp_path):
    assert load_mapping()["knobs"]["drain_cap_issues_per_run"] == DRAIN_CAP_ISSUES_PER_RUN == 20
    issues = [
        make_issue(9000 + i, "doom: forward", TS, login="flood")
        for i in range(1, 26)  # 25 valid issues
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 20
    assert [line.split()[-1] for line in lines] == [f"#{9000 + i}" for i in range(1, 21)]
    actions = load_actions(actions_path)
    touched = {m["issue"] for m in actions["moves"]} | set(post_push_by_issue(actions))
    for over_cap in range(9021, 9026):
        assert over_cap not in touched, "issues over the cap are left for the next run"


def test_close_duplicates_do_not_consume_the_cap(tmp_path):
    ledger = make_section_text(
        [ledger_line(TS, "old", "fire", 1, 100)], n=1
    )
    issues = [make_issue(100, "doom: fire", TS, login="old")] + [
        make_issue(9000 + i, "doom: back", TS, login="flood") for i in range(1, 21)
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    assert len(moves_path.read_text(encoding="ascii").splitlines()) == 20
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[100]["action"] == "close-duplicate"
    assert len(by_issue) == 21


# --- Reject handling: parser is the single source of truth --------------------

def test_invalid_title_is_close_rejected_with_the_parsers_fixed_message(tmp_path):
    hostile = "doom: forward && rm -rf /"
    issues = [make_issue(50, hostile, TS, login="mallory")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    entry = post_push_by_issue(load_actions(actions_path))[50]
    assert entry["action"] == "close-reject"
    parser_out = json_stdout(run_parser(hostile, tmp_path=tmp_path, transport="json"))
    assert entry["message"] == parser_out["message"]


def test_no_raw_title_bytes_ever_reach_the_output_files(tmp_path):
    hostile = "doom: forward `whoami` $(id) && rm -rf /"
    issues = [
        make_issue(60, hostile, TS, login="mallory"),
        make_issue(61, "doom: fire", TS, login="ok-player"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    for blob in (moves_path.read_bytes(), actions_path.read_bytes()):
        text = blob.decode("utf-8", errors="replace")
        assert hostile not in text
        for fragment in ("whoami", "$(id)", "rm -rf"):
            assert fragment not in text


def test_non_doom_issues_get_no_action_at_all(tmp_path):
    issues = [
        make_issue(70, "Bug report: profile typo", TS, login="reporter"),
        make_issue(71, "doom: use", TS, login="player-a"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    actions = load_actions(actions_path)
    touched = {m["issue"] for m in actions["moves"]} | set(post_push_by_issue(actions))
    assert 70 not in touched
    assert 71 in touched
    assert "Bug report" not in actions_path.read_text(encoding="utf-8")


# --- new-game cooldown (RFC D16, SPEC knob 30 min) ---------------------------

COOLDOWN_LEDGER = (
    make_section_text([
        ledger_line("2026-07-30T14:00:00Z", "alice", "forward", 1, 10),
        ledger_line("2026-07-30T15:00:00Z", "bob", "new-game", 1, 11),
    ], n=1)
    + make_section_text([], n=2)
)


def test_reset_within_30_minutes_of_last_reset_is_rejected_fixed_message(tmp_path):
    assert load_mapping()["knobs"]["new_game_cooldown_minutes"] == NEW_GAME_COOLDOWN_MINUTES == 30
    issues = [make_issue(30, "doom: new game", "2026-07-30T15:29:59Z", login="griefer")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, COOLDOWN_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    entry = post_push_by_issue(load_actions(actions_path))[30]
    assert entry["action"] == "close-reject"
    assert entry["message"], "cooldown reject must carry the fixed message"


def test_reset_at_exactly_30_minutes_is_accepted(tmp_path):
    issues = [make_issue(31, "doom: new game", "2026-07-30T15:30:00Z", login="player-b")]
    proc, moves_path, _ = run_drain(tmp_path, issues, COOLDOWN_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii") == (
        ledger_line("2026-07-30T15:30:00Z", "player-b", "new-game", 1, 31) + "\n"
    )


def test_cooldown_message_is_fixed_across_rejections(tmp_path):
    issues_a = [make_issue(32, "doom: new game", "2026-07-30T15:01:00Z", login="g1")]
    issues_b = [make_issue(33, "doom: new game", "2026-07-30T15:02:00Z", login="g2")]
    proc_a, _, actions_a = run_drain(tmp_path, issues_a, COOLDOWN_LEDGER)
    tmp2 = tmp_path / "b"
    proc_b, _, actions_b = run_drain(tmp2, issues_b, COOLDOWN_LEDGER)
    assert proc_a.returncode == 0, (proc_a.stdout, proc_a.stderr)
    assert proc_b.returncode == 0, (proc_b.stdout, proc_b.stderr)
    msg_a = post_push_by_issue(load_actions(actions_a))[32]["message"]
    msg_b = post_push_by_issue(load_actions(actions_b))[33]["message"]
    assert msg_a == msg_b and msg_a


def test_first_ever_game_has_no_cooldown(tmp_path):
    issues = [make_issue(34, "doom: new game", TS, login="starter")]
    proc, moves_path, _ = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii").endswith("new-game 1 #34\n")


def test_second_reset_in_one_run_hits_the_in_run_cooldown(tmp_path):
    issues = [
        make_issue(40, "doom: new game", "2026-07-30T16:00:00Z", login="p1"),
        make_issue(41, "doom: new game", "2026-07-30T16:05:00Z", login="p2"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 1 and lines[0].endswith("#40")
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[40]["action"] == "close-applied"
    assert by_issue[41]["action"] == "close-reject"


# --- Section cap (SPEC knob: 120,000 expanded frames) ------------------------

def at_cap_ledger():
    # 741 lines x (run-forward 18 frames x9) = 120,042 >= 120,000
    lines = [
        ledger_line("2026-07-30T10:00:00Z", "grinder", "run-forward", 9, i)
        for i in range(1, 742)
    ]
    return make_section_text(lines, n=1)


def below_cap_ledger():
    lines = [
        ledger_line("2026-07-30T10:00:00Z", "grinder", "run-forward", 9, i)
        for i in range(1, 741)
    ]  # 740 x 162 = 119,880 < 120,000
    return make_section_text(lines, n=1)


def test_at_section_cap_valid_moves_get_the_exact_log_full_guidance(tmp_path):
    assert load_mapping()["knobs"]["section_cap_frames"] == SECTION_CAP_FRAMES == 120_000
    issues = [make_issue(9001, "doom: forward", TS, login="late-player")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, at_cap_ledger())
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    entry = post_push_by_issue(load_actions(actions_path))[9001]
    assert entry["action"] == "close-reject"
    assert entry["message"] == LOG_FULL_MESSAGE


def test_below_the_cap_moves_are_still_accepted(tmp_path):
    issues = [make_issue(9002, "doom: forward", TS, login="player")]
    proc, moves_path, _ = run_drain(tmp_path, issues, below_cap_ledger())
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii").endswith("forward 1 #9002\n")


def test_at_cap_new_game_is_still_accepted(tmp_path):
    issues = [make_issue(9003, "doom: new game", TS, login="rescuer")]
    proc, moves_path, _ = run_drain(tmp_path, issues, at_cap_ledger())
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii").endswith("new-game 1 #9003\n")


def test_accepted_new_game_opens_a_fresh_section_within_the_run(tmp_path):
    """new-game (lower number) then forward (higher): both accepted — the
    forward lands in the fresh, empty section."""
    issues = [
        make_issue(9004, "doom: new game", TS, login="rescuer"),
        make_issue(9005, "doom: forward", "2026-07-30T14:03:00Z", login="player"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, at_cap_ledger())
    assert proc.returncode == 0
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("new-game 1 #9004")
    assert lines[1].endswith("forward 1 #9005")
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[9005]["action"] == "close-applied"


def test_move_numbered_before_an_at_cap_reset_is_rejected_first(tmp_path):
    """forward (lower number) processed before the reset: log-full reject;
    the later new-game is accepted. Ascending order is never re-shuffled."""
    issues = [
        make_issue(9006, "doom: forward", TS, login="unlucky"),
        make_issue(9007, "doom: new game", "2026-07-30T14:03:00Z", login="rescuer"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, at_cap_ledger())
    assert proc.returncode == 0
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 1 and lines[0].endswith("new-game 1 #9007")
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[9006]["action"] == "close-reject"
    assert by_issue[9006]["message"] == LOG_FULL_MESSAGE


# --- Handle sanitization ------------------------------------------------------

@pytest.mark.parametrize(
    ("login", "expected_handle"),
    [
        ("dependabot[bot]", "dependabotbot"),
        ("weird_user!!x", "weirduserx"),
        ("a" * 50, "a" * 39),
        ("<>!@", "player"),
    ],
    ids=["bot-brackets", "underscore-bang", "over-39-truncated", "all-stripped-fallback"],
)
def test_handles_are_sanitized_into_the_ledger_grammar(tmp_path, login, expected_handle):
    issues = [make_issue(80, "doom: fire", TS, login=login)]
    proc, moves_path, _ = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii") == (
        ledger_line(TS, expected_handle, "fire", 1, 80) + "\n"
    )


# --- Phase separation: closes strictly after push -----------------------------

def test_all_close_actions_live_under_the_post_push_phase(tmp_path):
    issues = [
        make_issue(90, "doom: fire", TS, login="a"),
        make_issue(91, "doom: nonsense", TS, login="b"),
    ]
    ledger = make_section_text([ledger_line(TS, "c", "use", 1, 89)], n=1)
    issues.append(make_issue(89, "doom: use", TS, login="c"))
    proc, _, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    actions = load_actions(actions_path)
    assert set(actions) == {"mapping_version", "moves", "post_push"}
    assert actions["mapping_version"] == 1
    for entry in actions["post_push"]:
        assert set(entry) == {"issue", "action", "message", "reason"}
        assert entry["action"] in {"close-applied", "close-duplicate", "close-reject"}
        assert entry["reason"] in REASON_CODES
    issues_in_post_push = [e["issue"] for e in actions["post_push"]]
    assert issues_in_post_push == sorted(issues_in_post_push)
    assert set(issues_in_post_push) == {89, 90, 91}
    for move in actions["moves"]:
        assert set(move) == {"issue", "token", "count"}


# --- Determinism and input hygiene -------------------------------------------

def test_drain_is_byte_deterministic_for_identical_inputs(tmp_path):
    issues = [
        make_issue(95, "doom: turn-right x3", TS, login="x-1"),
        make_issue(96, "doom: garbage", TS, login="x-2"),
    ]
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    proc_a, moves_a, actions_a = run_drain(a_dir, issues, EMPTY_LEDGER)
    proc_b, moves_b, actions_b = run_drain(b_dir, issues, EMPTY_LEDGER)
    assert proc_a.returncode == proc_b.returncode == 0
    assert moves_a.read_bytes() == moves_b.read_bytes()
    assert actions_a.read_bytes() == actions_b.read_bytes()


def test_malformed_issue_record_is_skipped_without_blocking_others(tmp_path):
    issues = [
        {"number": 200, "title": "doom: fire"},  # missing created_at and user
        make_issue(201, "doom: back", TS, login="fine"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 1 and lines[0].endswith("#201")
    assert 200 not in post_push_by_issue(load_actions(actions_path))


def test_corrupt_issues_json_is_exit_5(tmp_path):
    issues_path = tmp_path / "issues.json"
    issues_path.write_text("{not json", encoding="utf-8")
    ledger_path = tmp_path / "log.txt"
    ledger_path.write_text(EMPTY_LEDGER, encoding="ascii")
    from conftest import MAPPING_PATH, run_script
    proc = run_script(
        "drain.py",
        ["--issues", str(issues_path), "--ledger", str(ledger_path),
         "--mapping", str(MAPPING_PATH),
         "--toolchain", str(make_toolchain(tmp_path)),
         "--out-moves", str(tmp_path / "m.out"),
         "--out-actions", str(tmp_path / "a.json")],
    )
    assert proc.returncode == 5


def test_corrupt_ledger_is_exit_5_refuse_rather_than_guess(tmp_path):
    proc, _, _ = run_drain(
        tmp_path,
        [make_issue(1, "doom: fire", TS)],
        "this is not a valid game log\n",
    )
    assert proc.returncode == 5


# --- Machine-readable reason codes (workflow LOG_FULL wiring) -------------------

def test_section_cap_reject_carries_the_section_cap_reason_code(tmp_path):
    """The trigger .github/workflows/doom.yml needs to swap in the LOG_FULL
    state screen without re-deriving the SPEC section cap in YAML."""
    issues = [make_issue(9001, "doom: forward", TS, login="late-player")]
    proc, _, actions_path = run_drain(tmp_path, issues, at_cap_ledger())
    assert proc.returncode == 0
    entry = post_push_by_issue(load_actions(actions_path))[9001]
    assert entry["reason"] == REASON_SECTION_CAP
    assert entry["action"] == "close-reject"
    assert entry["message"] == LOG_FULL_MESSAGE, "message stays; reason is additive"


def test_section_cap_reason_is_distinguishable_from_a_grammar_reject(tmp_path):
    """Both are close-reject, so `action` alone cannot drive the state screen —
    this is precisely why the reason code exists."""
    issues = [
        make_issue(9001, "doom: forward", TS, login="capped"),
        make_issue(9002, "doom: nonsense", TS, login="typo"),
    ]
    proc, _, actions_path = run_drain(tmp_path, issues, at_cap_ledger())
    assert proc.returncode == 0
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[9001]["action"] == by_issue[9002]["action"] == "close-reject"
    assert by_issue[9001]["reason"] == REASON_SECTION_CAP
    assert by_issue[9002]["reason"] == REASON_GRAMMAR


def test_cooldown_reject_carries_the_cooldown_reason_code(tmp_path):
    issues = [make_issue(30, "doom: new game", "2026-07-30T15:29:59Z", login="griefer")]
    proc, _, actions_path = run_drain(tmp_path, issues, COOLDOWN_LEDGER)
    assert proc.returncode == 0
    entry = post_push_by_issue(load_actions(actions_path))[30]
    assert entry["reason"] == REASON_COOLDOWN
    assert entry["action"] == "close-reject"


def test_applied_and_duplicate_carry_their_reason_codes(tmp_path):
    ledger = make_section_text([ledger_line(TS, "old", "fire", 1, 100)], n=1)
    issues = [
        make_issue(100, "doom: fire", TS, login="old"),
        make_issue(101, "doom: back", TS, login="new"),
    ]
    proc, _, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[100]["reason"] == REASON_DUPLICATE
    assert by_issue[101]["reason"] == REASON_APPLIED


def test_every_reason_code_agrees_with_its_action(tmp_path):
    """reason and action must never disagree — the workflow trusts both."""
    ledger = make_section_text([ledger_line(TS, "old", "fire", 1, 100)], n=1)
    issues = [
        make_issue(100, "doom: fire", TS, login="old"),
        make_issue(101, "doom: back", TS, login="ok"),
        make_issue(102, "doom: jump", TS, login="typo"),
    ]
    proc, _, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    for entry in load_actions(actions_path)["post_push"]:
        assert entry["reason"] in REASON_CODES
        assert entry["action"] == ACTION_FOR_REASON[entry["reason"]], (
            f"issue {entry['issue']}: reason {entry['reason']!r} disagrees with "
            f"action {entry['action']!r}"
        )


# --- Sealed mode (SPEC 5.5, ratified 5e2c68f) -----------------------------------

SEALED_LEDGER = sealed_section_text(
    [ledger_line("2026-08-02T09:00:00Z", "earlier", "fire", 1, 5)]
)


def test_frame_contributing_move_is_sealed_rejected_with_the_verbatim_message(tmp_path):
    issues = [make_issue(19, "doom: fire", TS, login="player")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, SEALED_LEDGER)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert moves_path.read_bytes() == b""
    entry = post_push_by_issue(load_actions(actions_path))[19]
    assert entry["action"] == "close-reject"
    assert entry["reason"] == REASON_SEALED
    assert entry["message"] == SEALED_MESSAGE


def test_new_game_is_the_sole_admissible_move_while_sealed(tmp_path):
    issues = [make_issue(20, "doom: new game", TS, login="rescuer")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, SEALED_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii").endswith("new-game 1 #20\n")
    assert post_push_by_issue(load_actions(actions_path))[20]["reason"] == REASON_APPLIED


def test_sealed_rejects_do_not_block_a_later_new_game_in_the_same_batch(tmp_path):
    """THE livelock fix (SPEC 5.5 rule 3). The drain is ascending by issue
    number, so a frame-contributing move ahead of the reset must be rejected
    in-band — refusing the batch would re-refuse #19 forever and the game
    could never be rescued without a human closing it."""
    issues = [
        make_issue(19, "doom: fire", TS, login="unlucky"),
        make_issue(20, "doom: new game", "2026-08-02T14:05:00Z", login="rescuer"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, SEALED_LEDGER)
    assert proc.returncode == 0, "a sealed batch must never fail the run"
    lines = moves_path.read_text(encoding="ascii").splitlines()
    assert len(lines) == 1 and lines[0].endswith("new-game 1 #20")
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[19]["reason"] == REASON_SEALED
    assert by_issue[20]["reason"] == REASON_APPLIED


def test_run_with_only_sealed_rejects_is_a_success_with_zero_appends(tmp_path):
    """SPEC 5.5 rule 7 / section 10 degraded-mode note: nothing failed and no
    game state was eligible to change, so this is a success outcome."""
    issues = [
        make_issue(19, "doom: fire", TS, login="a"),
        make_issue(21, "doom: forward x3", TS, login="b"),
    ]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, SEALED_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b"", "zero ledger appends"
    actions = load_actions(actions_path)
    assert actions["moves"] == []
    assert {e["reason"] for e in actions["post_push"]} == {REASON_SEALED}


def test_cooldown_does_not_apply_while_sealed(tmp_path):
    """SPEC 5.5 rule 6: recovery must always be immediately reachable. A bump
    landing shortly after a reset must not strand the profile for 30 minutes."""
    ledger = sealed_section_text([
        ledger_line("2026-08-02T15:00:00Z", "bob", "new-game", 1, 11),
    ])
    issues = [make_issue(30, "doom: new game", "2026-08-02T15:00:30Z", login="rescuer")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii").endswith("new-game 1 #30\n")
    assert post_push_by_issue(load_actions(actions_path))[30]["reason"] == REASON_APPLIED


def test_cooldown_still_applies_when_the_section_is_not_sealed(tmp_path):
    """The bypass is scoped strictly to sealed mode — D16 is otherwise intact."""
    issues = [make_issue(30, "doom: new game", "2026-07-30T15:29:59Z", login="griefer")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, COOLDOWN_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    assert post_push_by_issue(load_actions(actions_path))[30]["reason"] == REASON_COOLDOWN


@pytest.mark.parametrize(
    ("pin", "override"),
    [("engine", {"engine": "99" * 20}), ("build", {"build": "88" * 32}),
     ("wad", {"wad": "77" * 32})],
    ids=["engine-commit-sha", "engine-build-sha256", "wad-sha256"],
)
def test_any_disagreeing_pin_seals_the_section(tmp_path, pin, override):
    toolchain = make_toolchain(tmp_path, **override)
    issues = [make_issue(19, "doom: fire", TS, login="player")]
    proc, moves_path, actions_path = run_drain(
        tmp_path, issues, EMPTY_LEDGER, toolchain=toolchain
    )
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    assert post_push_by_issue(load_actions(actions_path))[19]["reason"] == REASON_SEALED


def test_mapping_version_disagreement_seals_the_section(tmp_path):
    ledger = make_section_text([], n=1, mapping=2)
    issues = [make_issue(19, "doom: fire", TS, login="player")]
    proc, _, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    assert post_push_by_issue(load_actions(actions_path))[19]["reason"] == REASON_SEALED


def test_sealing_is_computed_from_the_current_section_not_the_first(tmp_path):
    """Archived sections legitimately carry the pins they were played under."""
    stale = sealed_section_text([
        ledger_line("2026-08-02T09:30:00Z", "carol", "new-game", 1, 6),
    ])
    ledger = stale + make_section_text([], n=2)
    issues = [make_issue(19, "doom: fire", TS, login="player")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, ledger)
    assert proc.returncode == 0
    assert moves_path.read_text(encoding="ascii").endswith("fire 1 #19\n")
    assert post_push_by_issue(load_actions(actions_path))[19]["reason"] == REASON_APPLIED


def test_sealed_is_distinguishable_from_section_cap_and_grammar(tmp_path):
    """All three are close-reject; only `reason` can drive the state screen."""
    issues = [make_issue(19, "doom: fire", TS, login="a"),
              make_issue(22, "doom: nonsense", TS, login="b")]
    proc, _, actions_path = run_drain(tmp_path, issues, SEALED_LEDGER)
    assert proc.returncode == 0
    by_issue = post_push_by_issue(load_actions(actions_path))
    assert by_issue[19]["action"] == by_issue[22]["action"] == "close-reject"
    assert by_issue[19]["reason"] == REASON_SEALED
    assert by_issue[22]["reason"] == REASON_GRAMMAR
    assert by_issue[19]["message"] != LOG_FULL_MESSAGE


def test_sealed_reject_message_carries_no_interpolation(tmp_path):
    issues = [make_issue(19, "doom: fire", TS, login="mallory")]
    proc, _, actions_path = run_drain(tmp_path, issues, SEALED_LEDGER)
    assert proc.returncode == 0
    message = post_push_by_issue(load_actions(actions_path))[19]["message"]
    assert message == SEALED_MESSAGE
    for leak in ("mallory", "99", "fire", "#19"):
        assert leak not in message


def test_zero_eligible_issues_yield_empty_outputs(tmp_path):
    issues = [make_issue(300, "Just a normal issue", TS, login="visitor")]
    proc, moves_path, actions_path = run_drain(tmp_path, issues, EMPTY_LEDGER)
    assert proc.returncode == 0
    assert moves_path.read_bytes() == b""
    actions = load_actions(actions_path)
    assert actions["moves"] == [] and actions["post_push"] == []
