"""
@spec-handoff
@interface expand.py --mapping PATH (--token ID --count N | --ledger FILE)
    [--expect-mapping-version V]; canonical stream text on stdout; exit 0 ok /
    2 usage (unknown token, count outside 1..9, bad args) / 3 mapping-version
    mismatch / 4 invalid mapping content / 5 invalid ledger input
@behavior
    - Move mode: the token's keys-frame repeated frames*count times, frames
      comma-joined, exactly one trailing LF; zero frames -> output is "\\n"
    - Ledger mode: FILE holds exactly ONE section (SPEC 5.2 header + 5.3 lines);
      stdout = the full stream (5.4) concatenating each line's expansion in
      ledger order, single "," joints, no inter-move padding; new-game lines
      contribute zero frames and NO empty frame or extra comma; the header's
      mapping= field must equal the mapping file's mapping_version else exit 3
    - Mapping is validated before any expansion: every keys char in
      {u,d,l,r,f,p,s} and unique within the frame (menu keys e/x structurally
      impossible) else exit 4; emitted frame keys are sorted ascending ASCII
      regardless of mapping order; all values loaded from the mapping file,
      never hardcoded; --expect-mapping-version V != file version -> exit 3
@edge-cases
    - Empty section -> "\\n" (zero frames, no commas, single LF); multi-section
      ledger input -> exit 5; malformed ledger line -> exit 5
@see game/SPEC.md sections 1, 2, 5; game/mapping/v1.json
"""

import pytest

from conftest import (
    TOKENS,
    V1_EXPANSION_ALPHABET,
    expected_stream_text,
    ledger_line,
    load_mapping,
    make_section_text,
    run_script,
    write_mapping,
)


def run_expand(*, token=None, count=None, ledger=None, mapping, expect_version=None):
    args = ["--mapping", str(mapping)]
    if token is not None:
        args += ["--token", token]
    if count is not None:
        args += ["--count", str(count)]
    if ledger is not None:
        args += ["--ledger", str(ledger)]
    if expect_version is not None:
        args += ["--expect-mapping-version", str(expect_version)]
    return run_script("expand.py", args)


@pytest.fixture()
def mapping_path():
    from conftest import MAPPING_PATH
    return MAPPING_PATH


# --- Move mode: frames per token, VERBATIM from the value table -------------

@pytest.mark.parametrize("token_id", sorted(TOKENS))
def test_single_move_expansion_matches_the_value_table(token_id, mapping_path):
    proc = run_expand(token=token_id, count=1, mapping=mapping_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.decode("ascii") == expected_stream_text([(token_id, 1)])


def test_forward_x5_expands_to_90_u_frames(mapping_path):
    """SPEC section 2 worked example: doom: forward x5 = 90 `u` frames."""
    proc = run_expand(token="forward", count=5, mapping=mapping_path)
    assert proc.returncode == 0
    text = proc.stdout.decode("ascii")
    assert text == ",".join(["u"] * 90) + "\n"
    assert text.count(",") == 89


def test_repeat_multiplies_the_full_sequence_consecutively(mapping_path):
    proc = run_expand(token="turn-left", count=2, mapping=mapping_path)
    assert proc.returncode == 0
    assert proc.stdout.decode("ascii") == ",".join(["l"] * 20) + "\n"


def test_run_forward_frames_are_canonical_su_never_us(mapping_path):
    proc = run_expand(token="run-forward", count=1, mapping=mapping_path)
    assert proc.returncode == 0
    text = proc.stdout.decode("ascii")
    assert text == ",".join(["su"] * 18) + "\n"
    assert "us" not in text


def test_new_game_expands_to_zero_frames_single_lf(mapping_path):
    proc = run_expand(token="new-game", count=1, mapping=mapping_path)
    assert proc.returncode == 0
    assert proc.stdout == b"\n"


@pytest.mark.parametrize("token_id", sorted(TOKENS))
def test_no_expansion_ever_emits_menu_keys_e_or_x(token_id, mapping_path):
    """Asserted over the whole mapping: e/x are unexpandable by construction."""
    proc = run_expand(token=token_id, count=1, mapping=mapping_path)
    assert proc.returncode == 0
    payload = proc.stdout.decode("ascii").rstrip("\n").replace(",", "")
    assert "e" not in payload and "x" not in payload
    assert set(payload) <= V1_EXPANSION_ALPHABET


def test_mapping_file_contains_no_e_or_x_key_characters():
    """SPEC section 1 bullet: v1.json contains no e/x key chars. Rides with a
    script call (red until E4) so the whole file stays missing-implementation red."""
    mapping = load_mapping()
    for entry in mapping["tokens"]:
        assert "e" not in entry["keys"] and "x" not in entry["keys"]
        assert set(entry["keys"]) <= V1_EXPANSION_ALPHABET
    from conftest import MAPPING_PATH
    proc = run_expand(token="fire", count=1, mapping=MAPPING_PATH)
    assert proc.returncode == 0


# --- Defensive bounds in move mode ------------------------------------------

def test_count_zero_is_a_usage_error(mapping_path):
    assert run_expand(token="forward", count=0, mapping=mapping_path).returncode == 2


def test_count_ten_is_a_usage_error(mapping_path):
    assert run_expand(token="forward", count=10, mapping=mapping_path).returncode == 2


def test_unknown_token_is_a_usage_error(mapping_path):
    assert run_expand(token="jump", count=1, mapping=mapping_path).returncode == 2


# --- Mapping validation: fail closed ----------------------------------------

def _doctored(token_id, keys):
    doc = load_mapping()
    for entry in doc["tokens"]:
        if entry["id"] == token_id:
            entry["keys"] = keys
    return doc


def test_mapping_entry_containing_e_is_refused(tmp_path, mapping_path):
    path = write_mapping(tmp_path, _doctored("fire", "fe"))
    assert run_expand(token="fire", count=1, mapping=path).returncode == 4


def test_mapping_entry_containing_x_is_refused(tmp_path, mapping_path):
    path = write_mapping(tmp_path, _doctored("use", "x"))
    assert run_expand(token="use", count=1, mapping=path).returncode == 4


def test_mapping_entry_outside_v1_alphabet_is_refused(tmp_path, mapping_path):
    path = write_mapping(tmp_path, _doctored("forward", "<"))
    assert run_expand(token="forward", count=1, mapping=path).returncode == 4


def test_mapping_entry_with_digit_key_is_refused(tmp_path, mapping_path):
    path = write_mapping(tmp_path, _doctored("forward", "9"))
    assert run_expand(token="forward", count=1, mapping=path).returncode == 4


def test_mapping_entry_with_duplicate_keys_in_frame_is_refused(tmp_path, mapping_path):
    path = write_mapping(tmp_path, _doctored("forward", "uu"))
    assert run_expand(token="forward", count=1, mapping=path).returncode == 4


def test_unsorted_mapping_keys_are_emitted_in_canonical_ascii_order(tmp_path, mapping_path):
    """SPEC 5.4: ascending ASCII within a frame (su, never us) -- the expander
    canonicalizes on emit even if a mapping entry is stored unsorted."""
    path = write_mapping(tmp_path, _doctored("run-forward", "us"))
    proc = run_expand(token="run-forward", count=1, mapping=path)
    assert proc.returncode == 0
    assert proc.stdout.decode("ascii") == ",".join(["su"] * 18) + "\n"


# --- Mapping-version refusal -------------------------------------------------

def test_expect_mapping_version_mismatch_is_refused_exit_3(mapping_path):
    assert run_expand(token="forward", count=1, mapping=mapping_path,
                      expect_version=2).returncode == 3


def test_expect_mapping_version_match_is_accepted(mapping_path):
    proc = run_expand(token="forward", count=1, mapping=mapping_path, expect_version=1)
    assert proc.returncode == 0


def test_ledger_header_mapping_version_mismatch_is_refused_exit_3(tmp_path, mapping_path):
    section = make_section_text(
        [ledger_line("2026-07-30T14:02:11Z", "nikitastetskiy", "forward", 5, 17)],
        mapping=2,
    )
    path = tmp_path / "section.txt"
    path.write_text(section, encoding="ascii")
    assert run_expand(ledger=path, mapping=mapping_path).returncode == 3


# --- Ledger mode -------------------------------------------------------------

def test_ledger_section_expands_to_spec_worked_example_byte_exact(tmp_path, mapping_path):
    """SPEC 5.4 worked example: fire 1 then turn-left 2 => 28 frames, 27 commas."""
    section = make_section_text([
        ledger_line("2026-07-30T14:02:11Z", "alice", "fire", 1, 1),
        ledger_line("2026-07-30T14:03:00Z", "bob", "turn-left", 2, 2),
    ])
    path = tmp_path / "section.txt"
    path.write_text(section, encoding="ascii")
    proc = run_expand(ledger=path, mapping=mapping_path)
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout.decode("ascii")
    assert text == expected_stream_text([("fire", 1), ("turn-left", 2)])
    frames = text.rstrip("\n").split(",")
    assert len(frames) == 28
    assert text.count(",") == 27


def test_new_game_final_line_adds_no_empty_frame_or_comma(tmp_path, mapping_path):
    """A v1-generated stream must never contain an empty frame (SPEC 5.4)."""
    section = make_section_text([
        ledger_line("2026-07-30T14:02:11Z", "alice", "fire", 1, 1),
        ledger_line("2026-07-30T15:00:00Z", "somevisitor", "new-game", 1, 23),
    ])
    path = tmp_path / "section.txt"
    path.write_text(section, encoding="ascii")
    proc = run_expand(ledger=path, mapping=mapping_path)
    assert proc.returncode == 0
    text = proc.stdout.decode("ascii")
    assert text == ",".join(["f"] * 8) + "\n"
    assert ",," not in text and not text.rstrip("\n").endswith(",")


def test_empty_section_expands_to_empty_stream_single_lf(tmp_path, mapping_path):
    """SPEC 5.1: empty section => zero frames, no commas, single LF."""
    path = tmp_path / "section.txt"
    path.write_text(make_section_text([]), encoding="ascii")
    proc = run_expand(ledger=path, mapping=mapping_path)
    assert proc.returncode == 0
    assert proc.stdout == b"\n"


def test_multi_section_ledger_input_is_refused_exit_5(tmp_path, mapping_path):
    two = (
        make_section_text([ledger_line("2026-07-30T15:00:00Z", "a", "new-game", 1, 3)], n=1)
        + make_section_text([], n=2)
    )
    path = tmp_path / "two.txt"
    path.write_text(two, encoding="ascii")
    assert run_expand(ledger=path, mapping=mapping_path).returncode == 5


def test_malformed_ledger_line_is_refused_exit_5(tmp_path, mapping_path):
    path = tmp_path / "bad.txt"
    path.write_text(make_section_text(["this is not a ledger line"]), encoding="ascii")
    assert run_expand(ledger=path, mapping=mapping_path).returncode == 5


def test_expansion_is_deterministic_across_invocations(tmp_path, mapping_path):
    section = make_section_text([
        ledger_line("2026-07-30T14:02:11Z", "alice", "run-forward", 9, 40),
    ])
    path = tmp_path / "section.txt"
    path.write_text(section, encoding="ascii")
    a = run_expand(ledger=path, mapping=mapping_path)
    b = run_expand(ledger=path, mapping=mapping_path)
    assert a.returncode == b.returncode == 0
    assert a.stdout == b.stdout
