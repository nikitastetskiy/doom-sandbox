"""
@spec-handoff
@interface parse_title.py [--json FILE] [--mapping PATH]; title via env DOOM_TITLE
    (set-but-empty = empty title) or --json {"title": <str>} \u2014 the title is NEVER
    an argv value; exit 0 accept / 1 reject / 2 transport error (no title source,
    unreadable JSON, missing or non-string "title" key)
@behavior
    - stdout is one JSON object. Accept: {"ok": true, "token": <id>, "count": <1-9>}
      and nothing else \u2014 the raw title is never echoed anywhere, accept or reject
    - Byte-level checks in order: empty -> too-long (> 64 bytes) -> non-ascii (any
      byte > 0x7F) -> bare-prefix (exactly "doom:" or "doom: ") -> full-string set
      membership in the 56 canonical_titles of game/mapping/v1.json; any other
      miss -> reject_class "unlisted-token". No unicode normalization, no case
      folding, no trimming. Reject: {"ok": false, "reject_class": <class>,
      "message": <fixed per-class string containing no input bytes>}
@edge-cases
    - "doom: new game x2" -> unlisted-token (SPEC 2.1 exact-literal, no suffix);
      trailing space/newline/CR -> reject (anchored \\A...\\z semantics); a 64-byte
      non-canonical title -> unlisted-token (length gate passes at exactly 64)
@see game/SPEC.md sections 1-4; game/mapping/v1.json; RFC 001 normative contracts 1-2
"""

import json

import pytest

from conftest import (
    CANONICAL_TITLE_COUNT,
    REPEAT_MAX,
    REPEAT_MIN,
    TITLE_BYTE_CAP,
    TOKENS,
    canonical_expected,
    json_stdout,
    load_mapping,
    run_parser,
)

CANONICAL = canonical_expected()


# --- Positive cases: the full 56-literal canonical set ----------------------

@pytest.mark.parametrize(
    ("title", "token", "count"),
    [(t, tc[0], tc[1]) for t, tc in sorted(CANONICAL.items())],
    ids=lambda v: repr(v) if isinstance(v, str) else None,
)
def test_every_canonical_title_is_accepted_with_its_token_and_count(title, token, count):
    proc = run_parser(title, transport="env")
    assert proc.returncode == 0, f"expected accept for {title!r}: {proc.stdout!r} {proc.stderr!r}"
    out = json_stdout(proc)
    assert out["ok"] is True
    assert out["token"] == token
    assert out["count"] == count


def test_canonical_set_has_exactly_56_titles_and_mapping_lists_them_all():
    """SPEC section 3: 8 base literals + 6 repeatable x counts 2-9 = 56.

    Doubles as the value-table consumption test: game/mapping/v1.json
    canonical_titles must equal the generated set exactly, and every one of
    them must parse. Red until parse_title.py exists.
    """
    generated = set(CANONICAL)
    assert len(generated) == CANONICAL_TITLE_COUNT == 56
    mapping = load_mapping()
    listed = mapping["canonical_titles"]
    assert len(listed) == 56
    assert set(listed) == generated
    proc = run_parser("doom: new game", transport="env")
    assert proc.returncode == 0
    assert json_stdout(proc)["token"] == "new-game"


def test_repeat_lower_bound_x2_is_accepted():
    proc = run_parser("doom: forward x2", transport="env")
    assert proc.returncode == 0
    out = json_stdout(proc)
    assert (out["token"], out["count"]) == ("forward", REPEAT_MIN)


def test_repeat_upper_bound_x9_is_accepted():
    proc = run_parser("doom: run-forward x9", transport="env")
    assert proc.returncode == 0
    out = json_stdout(proc)
    assert (out["token"], out["count"]) == ("run-forward", REPEAT_MAX)


def test_base_literal_yields_count_1_not_0(tmp_path):
    proc = run_parser("doom: use", tmp_path=tmp_path)
    assert proc.returncode == 0
    out = json_stdout(proc)
    assert (out["token"], out["count"]) == ("use", 1)


def test_json_file_transport_accepts_canonical_title(tmp_path):
    proc = run_parser("doom: fire x3", tmp_path=tmp_path, transport="json")
    assert proc.returncode == 0
    out = json_stdout(proc)
    assert (out["token"], out["count"]) == ("fire", 3)


# --- Enumerated reject classes (SPEC section 4 -- every class covered) ------

REJECTS = [
    # empty title
    ("empty-string", "", "empty"),
    # > 64 bytes (title byte cap; the parser bounds itself below GitHub's ~256)
    ("65-bytes-doom-prefixed", "doom: forward" + "a" * 52, "too-long"),
    ("100-bytes-plain", "d" * 100, "too-long"),
    # any non-ASCII byte -- no normalization, homoglyphs fail closed
    ("cyrillic-o-homoglyph", "doom: f\u043erward", "non-ascii"),
    ("fullwidth-x-repeat", "doom: forward \uff582", "non-ascii"),
    ("multiplication-sign-repeat", "doom: forward \u00d72", "non-ascii"),
    ("nbsp-separator", "doom:\u00a0forward", "non-ascii"),
    ("zero-width-space-suffix", "doom: forward\u200b", "non-ascii"),
    ("emoji-payload", "doom: fire \U0001f52b", "non-ascii"),
    # bare prefix
    ("bare-doom-colon", "doom:", "bare-prefix"),
    ("bare-doom-colon-space", "doom: ", "bare-prefix"),
    # unlisted token
    ("unknown-token-jump", "doom: jump", "unlisted-token"),
    ("unknown-token-strafe", "doom: strafe-left", "unlisted-token"),
    ("plural-token", "doom: forwards", "unlisted-token"),
    ("capitalized-token", "doom: Forward", "unlisted-token"),
    ("uppercase-prefix", "DOOM: forward", "unlisted-token"),
    ("titlecase-prefix", "Doom: forward", "unlisted-token"),
    ("hyphenated-new-game", "doom: new-game", "unlisted-token"),
    ("space-run-forward", "doom: run forward", "unlisted-token"),
    ("no-space-after-colon", "doom:forward", "unlisted-token"),
    ("not-a-command-at-all", "hello", "unlisted-token"),
    ("whitespace-only", " ", "unlisted-token"),
    ("bare-word-doom", "doom", "unlisted-token"),
    # malformed or out-of-bounds repeat
    ("repeat-x1-invalid", "doom: forward x1", "unlisted-token"),
    ("repeat-x0-invalid", "doom: forward x0", "unlisted-token"),
    ("repeat-x10-multi-digit", "doom: forward x10", "unlisted-token"),
    ("repeat-x05-padded", "doom: forward x05", "unlisted-token"),
    ("repeat-x-3-signed", "doom: forward x-3", "unlisted-token"),
    ("repeat-xa-non-numeric", "doom: forward xa", "unlisted-token"),
    ("repeat-bare-x", "doom: forward x", "unlisted-token"),
    ("repeat-x2.5-fractional", "doom: forward x2.5", "unlisted-token"),
    ("repeat-missing-space", "doom: forwardx2", "unlisted-token"),
    ("repeat-double-space", "doom: forward  x2", "unlisted-token"),
    ("repeat-space-inside", "doom: forward x 2", "unlisted-token"),
    ("repeat-uppercase-x", "doom: forward X2", "unlisted-token"),
    ("repeat-on-non-repeatable-use", "doom: use x2", "unlisted-token"),
    # prefix + trailing garbage (anchored full-string match)
    ("shell-and-and-rm", "doom: forward && rm -rf /", "unlisted-token"),
    ("shell-semicolon", "doom: forward; ls", "unlisted-token"),
    ("shell-pipe", "doom: forward | cat", "unlisted-token"),
    ("shell-backticks", "doom: forward `whoami`", "unlisted-token"),
    ("shell-dollar-paren", "doom: forward $(id)", "unlisted-token"),
    ("trailing-space", "doom: forward ", "unlisted-token"),
    ("leading-space", " doom: forward", "unlisted-token"),
    ("trailing-newline", "doom: forward\n", "unlisted-token"),
    ("trailing-cr", "doom: forward\r", "unlisted-token"),
    ("trailing-crlf", "doom: forward\r\n", "unlisted-token"),
    ("leading-newline", "\ndoom: forward", "unlisted-token"),
    ("trailing-comment", "doom: forward #1", "unlisted-token"),
    ("prefixed-garbage", "xdoom: forward", "unlisted-token"),
    # duplicated / conflicting combos
    ("two-tokens", "doom: forward back", "unlisted-token"),
    ("double-repeat", "doom: forward x2 x3", "unlisted-token"),
    ("doubled-command", "doom: forward doom: back", "unlisted-token"),
    ("doubled-token-word", "doom: use use", "unlisted-token"),
]


@pytest.mark.parametrize(
    ("title", "reject_class"),
    [(title, cls) for _, title, cls in REJECTS],
    ids=[case_id for case_id, _, _ in REJECTS],
)
def test_reject_class_is_reported_and_exit_code_is_1(title, reject_class, tmp_path):
    proc = run_parser(title, tmp_path=tmp_path, transport="json")
    assert proc.returncode == 1, (
        f"expected reject for {title!r}: rc={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    out = json_stdout(proc)
    assert out["ok"] is False
    assert out["reject_class"] == reject_class


def test_new_game_with_repeat_suffix_is_rejected_not_repeated():
    """SPEC 2.1: `doom: new game x2` is a reject (unlisted-token class), never
    'new game twice' \u2014 exact-literal set membership, no tokenizing."""
    proc = run_parser("doom: new game x2", transport="env")
    assert proc.returncode == 1
    out = json_stdout(proc)
    assert out["ok"] is False
    assert out["reject_class"] == "unlisted-token"


def test_new_game_with_trailing_space_is_rejected():
    proc = run_parser("doom: new game ", transport="env")
    assert proc.returncode == 1
    assert json_stdout(proc)["ok"] is False


def test_title_of_exactly_64_bytes_passes_the_length_gate():
    """The cap rejects titles LONGER than 64 bytes; exactly 64 proceeds to set
    membership (and fails there for a non-canonical string)."""
    title = "doom: " + "a" * 58
    assert len(title.encode("utf-8")) == TITLE_BYTE_CAP
    proc = run_parser(title, transport="env")
    assert proc.returncode == 1
    assert json_stdout(proc)["reject_class"] == "unlisted-token"


def test_title_of_65_bytes_is_rejected_too_long():
    title = "doom: " + "a" * 59
    assert len(title.encode("utf-8")) == TITLE_BYTE_CAP + 1
    proc = run_parser(title, transport="env")
    assert proc.returncode == 1
    assert json_stdout(proc)["reject_class"] == "too-long"


def test_non_ascii_rejected_via_env_transport_too():
    proc = run_parser("doom: f\u043erward", transport="env")
    assert proc.returncode == 1
    assert json_stdout(proc)["reject_class"] == "non-ascii"


# --- Output hygiene: no echo, fixed messages, minimal surface ---------------

HOSTILE_TITLES = [
    "doom: forward && rm -rf /",
    "doom: forward `whoami`",
    "doom: forward $(id)",
    "doom: forward <img src=x onerror=alert(1)>",
    "doom: forward ../../etc/passwd",
]


@pytest.mark.parametrize("title", HOSTILE_TITLES, ids=lambda t: repr(t))
def test_reject_output_never_echoes_the_input_title(title, tmp_path):
    proc = run_parser(title, tmp_path=tmp_path, transport="json")
    assert proc.returncode == 1
    combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    assert title not in combined
    for fragment in ("rm -rf", "whoami", "$(id)", "onerror", "etc/passwd"):
        assert fragment not in combined


def test_accept_output_contains_only_ok_token_count_and_no_title_echo():
    proc = run_parser("doom: turn-left x3", transport="env")
    assert proc.returncode == 0
    out = json_stdout(proc)
    assert set(out) == {"ok", "token", "count"}
    assert "doom: " not in proc.stdout.decode("utf-8")
    assert proc.stderr == b""


def test_reject_message_is_fixed_within_a_class_and_carries_no_input(tmp_path):
    first = json_stdout(run_parser("doom: jump", tmp_path=tmp_path, transport="json"))
    second = json_stdout(run_parser("doom: teleport", tmp_path=tmp_path, transport="json"))
    assert first["message"] == second["message"]
    assert first["message"]  # non-empty fixed string
    assert "jump" not in first["message"] and "teleport" not in second["message"]

    non_ascii_a = json_stdout(run_parser("doom: f\u043erward", tmp_path=tmp_path, transport="json"))
    non_ascii_b = json_stdout(run_parser("doom: \u00d7", tmp_path=tmp_path, transport="json"))
    assert non_ascii_a["message"] == non_ascii_b["message"]


def test_parse_is_deterministic_across_invocations():
    a = run_parser("doom: back x4", transport="env")
    b = run_parser("doom: back x4", transport="env")
    assert (a.returncode, a.stdout) == (b.returncode, b.stdout)
    c = run_parser("doom: back x40", transport="env")
    d = run_parser("doom: back x40", transport="env")
    assert (c.returncode, c.stdout) == (d.returncode, d.stdout)


# --- Transport contract -----------------------------------------------------

def test_env_transport_set_but_empty_is_an_empty_title_reject_not_transport_error():
    proc = run_parser("", transport="env")
    assert proc.returncode == 1
    assert json_stdout(proc)["reject_class"] == "empty"


def test_json_transport_empty_title_is_an_empty_reject(tmp_path):
    proc = run_parser("", tmp_path=tmp_path, transport="json")
    assert proc.returncode == 1
    assert json_stdout(proc)["reject_class"] == "empty"


def test_no_title_source_at_all_is_a_transport_error_exit_2():
    proc = run_parser(transport="none")
    assert proc.returncode == 2


def test_json_transport_missing_title_key_is_a_transport_error(tmp_path):
    payload = tmp_path / "bad.json"
    payload.write_text(json.dumps({"not_title": "doom: forward"}), encoding="utf-8")
    proc = run_parser(transport="none", extra_args=("--json", str(payload)))
    assert proc.returncode == 2


def test_json_transport_non_string_title_is_a_transport_error(tmp_path):
    payload = tmp_path / "bad.json"
    payload.write_text(json.dumps({"title": 123}), encoding="utf-8")
    proc = run_parser(transport="none", extra_args=("--json", str(payload)))
    assert proc.returncode == 2


def test_json_transport_unreadable_file_is_a_transport_error(tmp_path):
    payload = tmp_path / "broken.json"
    payload.write_text("{not json", encoding="utf-8")
    proc = run_parser(transport="none", extra_args=("--json", str(payload)))
    assert proc.returncode == 2


# --- Value-table sanity pinned against SPEC section 1 -----------------------

def test_mapping_token_table_matches_spec_section_1_values():
    """Frames/keys/repeatable per token, consumed VERBATIM. Runs the parser on
    one representative title so the test is red until E4 (data assertions ride
    along and keep guarding after green)."""
    mapping = load_mapping()
    by_id = {t["id"]: t for t in mapping["tokens"]}
    assert set(by_id) == set(TOKENS)
    for token_id, spec in TOKENS.items():
        entry = by_id[token_id]
        assert entry["title"] == spec["title"]
        assert entry["keys"] == spec["keys"]
        assert entry["frames"] == spec["frames"]
        assert entry["repeatable"] is spec["repeatable"]
    assert mapping["mapping_version"] == 1
    assert mapping["repeat"] == {"min": REPEAT_MIN, "max": REPEAT_MAX}
    assert mapping["knobs"]["title_byte_cap"] == TITLE_BYTE_CAP
    proc = run_parser("doom: forward", transport="env")
    assert proc.returncode == 0
    assert json_stdout(proc)["token"] == "forward"
