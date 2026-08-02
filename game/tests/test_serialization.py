"""
@spec-handoff
@interface gamelog.py (importable module): parse_log(text)->Log with
    .sections[{header:{n,engine,build,wad,mapping}, entries:[{ts,handle,token,
    count,issue}]}], render_log(log)->text, parse_header/render_header,
    parse_ledger_line/render_ledger_line, parse_stream(text)->list[str],
    render_stream(frames)->text; every grammar violation raises ValueError
@behavior
    - Byte-exact round-trips on the valid domain: render(parse(x)) == x and
      parse(render(v)) == v; ASCII only, LF only, exactly one trailing LF,
      no tabs, single 0x20 separators
    - Header: "#section <n> engine=<40-lohex> build=<64-lohex> wad=<64-lohex>
      mapping=<int>"; n starts at 1 and increases by exactly 1 across a file
    - Ledger line: "<YYYY-MM-DDTHH:MM:SSZ> <handle> <token-id> <count> #<issue>";
      handle [a-zA-Z0-9-]{1,39}; token from the 8-id closed set; count 1-9 with
      use/new-game fixed at 1; issue decimal >= 1, no leading zeros
    - Stream: frame chars from {u,d,l,r,f,p,s,<,>,0-9} (e/x invalid), unique +
      ascending ASCII within a frame; N frames = N-1 commas, no comma before
      the final LF; "u,,u\\n" == exactly 3 frames; "\\n" == zero frames
@edge-cases
    - render_stream([""]) or a trailing-empty frame -> ValueError (both are
      byte-unrepresentable under the empty-file / no-trailing-separator rules);
      CRLF, zero or two trailing LFs, uppercase hex, tab separators, a ledger
      line before any header -> ValueError
@see game/SPEC.md section 5; game/scripts/expand.py (stream==expand invariant)
"""

import pytest

from conftest import (
    BUILD_HEX,
    ENGINE_HEX,
    WAD_HEX,
    expected_stream_text,
    import_gamelog,
    ledger_line,
    make_section_text,
    run_script,
    section_header,
)

SPEC_LEDGER_EXAMPLE = "2026-07-30T14:02:11Z nikitastetskiy forward 5 #17"
SPEC_RESET_EXAMPLE = "2026-07-30T15:00:00Z somevisitor new-game 1 #23"


# --- Ledger line grammar (SPEC 5.3) -----------------------------------------

def test_spec_ledger_line_example_parses_and_round_trips_byte_exact():
    gamelog = import_gamelog()
    entry = gamelog.parse_ledger_line(SPEC_LEDGER_EXAMPLE)
    assert entry.ts == "2026-07-30T14:02:11Z"
    assert entry.handle == "nikitastetskiy"
    assert entry.token == "forward"
    assert entry.count == 5
    assert entry.issue == 17
    assert gamelog.render_ledger_line(entry) == SPEC_LEDGER_EXAMPLE


def test_spec_reset_line_example_parses_and_round_trips_byte_exact():
    gamelog = import_gamelog()
    entry = gamelog.parse_ledger_line(SPEC_RESET_EXAMPLE)
    assert (entry.token, entry.count, entry.issue) == ("new-game", 1, 23)
    assert gamelog.render_ledger_line(entry) == SPEC_RESET_EXAMPLE


BAD_LEDGER_LINES = [
    ("timestamp-no-z", "2026-07-30T14:02:11 nikitastetskiy forward 5 #17"),
    ("timestamp-millis", "2026-07-30T14:02:11.123Z nik forward 5 #17"),
    ("timestamp-date-only", "2026-07-30 nik forward 5 #17"),
    ("timestamp-lowercase-t", "2026-07-30t14:02:11Z nik forward 5 #17"),
    ("timestamp-impossible-date", "2026-13-40T25:61:61Z nik forward 5 #17"),
    ("handle-40-chars", f"2026-07-30T14:02:11Z {'h' * 40} forward 5 #17"),
    ("handle-underscore", "2026-07-30T14:02:11Z bad_handle forward 5 #17"),
    ("handle-at-prefixed", "2026-07-30T14:02:11Z @nik forward 5 #17"),
    ("handle-empty-double-space", "2026-07-30T14:02:11Z  forward 5 #17"),
    ("token-unlisted", "2026-07-30T14:02:11Z nik jump 5 #17"),
    ("token-title-not-id", "2026-07-30T14:02:11Z nik new game 1 #17"),
    ("count-zero", "2026-07-30T14:02:11Z nik forward 0 #17"),
    ("count-ten", "2026-07-30T14:02:11Z nik forward 10 #17"),
    ("count-padded", "2026-07-30T14:02:11Z nik forward 02 #17"),
    ("count-2-on-use", "2026-07-30T14:02:11Z nik use 2 #17"),
    ("count-2-on-new-game", "2026-07-30T14:02:11Z nik new-game 2 #17"),
    ("issue-missing-hash", "2026-07-30T14:02:11Z nik forward 5 17"),
    ("issue-zero", "2026-07-30T14:02:11Z nik forward 5 #0"),
    ("issue-leading-zero", "2026-07-30T14:02:11Z nik forward 5 #017"),
    ("issue-negative", "2026-07-30T14:02:11Z nik forward 5 #-5"),
    ("issue-trailing-junk", "2026-07-30T14:02:11Z nik forward 5 #1x"),
    ("missing-field", "2026-07-30T14:02:11Z nik forward #17"),
    ("extra-field", "2026-07-30T14:02:11Z nik forward 5 #17 extra"),
    ("tab-separator", "2026-07-30T14:02:11Z\tnik\tforward\t5\t#17"),
    ("double-space-separator", "2026-07-30T14:02:11Z nik  forward 5 #17"),
]


@pytest.mark.parametrize(
    "line", [line for _, line in BAD_LEDGER_LINES], ids=[i for i, _ in BAD_LEDGER_LINES]
)
def test_invalid_ledger_line_raises_value_error(line):
    gamelog = import_gamelog()
    with pytest.raises(ValueError):
        gamelog.parse_ledger_line(line)


def test_count_9_on_repeatable_token_is_valid():
    gamelog = import_gamelog()
    entry = gamelog.parse_ledger_line("2026-07-30T14:02:11Z nik fire 9 #99")
    assert (entry.token, entry.count) == ("fire", 9)


# --- Section header grammar (SPEC 5.2) --------------------------------------

def test_section_header_parses_and_round_trips_byte_exact():
    gamelog = import_gamelog()
    line = section_header(n=1)
    header = gamelog.parse_header(line)
    assert header.n == 1
    assert header.engine == ENGINE_HEX
    assert header.build == BUILD_HEX
    assert header.wad == WAD_HEX
    assert header.mapping == 1
    assert gamelog.render_header(header) == line


BAD_HEADERS = [
    ("engine-39-hex", f"#section 1 engine={'a' * 39} build={BUILD_HEX} wad={WAD_HEX} mapping=1"),
    ("build-63-hex", f"#section 1 engine={ENGINE_HEX} build={'b' * 63} wad={WAD_HEX} mapping=1"),
    ("wad-65-hex", f"#section 1 engine={ENGINE_HEX} build={BUILD_HEX} wad={'c' * 65} mapping=1"),
    ("uppercase-hex", f"#section 1 engine={'AB' * 20} build={BUILD_HEX} wad={WAD_HEX} mapping=1"),
    ("non-hex-chars", f"#section 1 engine={'zz' * 20} build={BUILD_HEX} wad={WAD_HEX} mapping=1"),
    ("section-zero", f"#section 0 engine={ENGINE_HEX} build={BUILD_HEX} wad={WAD_HEX} mapping=1"),
    ("section-negative", f"#section -1 engine={ENGINE_HEX} build={BUILD_HEX} wad={WAD_HEX} mapping=1"),
    ("missing-mapping-field", f"#section 1 engine={ENGINE_HEX} build={BUILD_HEX} wad={WAD_HEX}"),
    ("extra-field", f"#section 1 engine={ENGINE_HEX} build={BUILD_HEX} wad={WAD_HEX} mapping=1 x=y"),
    ("wrong-tag", f"#sect 1 engine={ENGINE_HEX} build={BUILD_HEX} wad={WAD_HEX} mapping=1"),
    ("reordered-fields", f"#section 1 build={BUILD_HEX} engine={ENGINE_HEX} wad={WAD_HEX} mapping=1"),
]


@pytest.mark.parametrize(
    "line", [line for _, line in BAD_HEADERS], ids=[i for i, _ in BAD_HEADERS]
)
def test_invalid_section_header_raises_value_error(line):
    gamelog = import_gamelog()
    with pytest.raises(ValueError):
        gamelog.parse_header(line)


# --- Full log files (SPEC 5.1) ----------------------------------------------

def test_multi_section_log_round_trips_byte_exact():
    gamelog = import_gamelog()
    text = (
        make_section_text([
            ledger_line("2026-07-30T14:02:11Z", "nikitastetskiy", "forward", 5, 17),
            SPEC_RESET_EXAMPLE,
        ], n=1)
        + make_section_text([
            ledger_line("2026-07-30T15:05:00Z", "carol", "fire", 3, 24),
        ], n=2)
    )
    log = gamelog.parse_log(text)
    assert [s.header.n for s in log.sections] == [1, 2]
    assert [len(s.entries) for s in log.sections] == [2, 1]
    assert gamelog.render_log(log) == text


def test_empty_section_fresh_game_is_valid():
    gamelog = import_gamelog()
    text = make_section_text([], n=1)
    log = gamelog.parse_log(text)
    assert len(log.sections) == 1 and log.sections[0].entries == []
    assert gamelog.render_log(log) == text


@pytest.mark.parametrize(
    ("case_id", "build"),
    [
        ("ledger-line-before-any-header", lambda: SPEC_LEDGER_EXAMPLE + "\n"),
        ("first-section-not-1", lambda: make_section_text([], n=2)),
        ("section-gap-1-then-3", lambda: make_section_text([], n=1) + make_section_text([], n=3)),
        ("duplicate-section-number", lambda: make_section_text([], n=1) + make_section_text([], n=1)),
        ("no-trailing-lf", lambda: make_section_text([], n=1)[:-1]),
        ("two-trailing-lfs", lambda: make_section_text([], n=1) + "\n"),
        ("crlf-newlines", lambda: make_section_text([], n=1).replace("\n", "\r\n")),
        ("non-ascii-byte", lambda: make_section_text(
            [ledger_line("2026-07-30T14:02:11Z", "niké", "forward", 1, 5)], n=1)),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_invalid_log_file_raises_value_error(case_id, build):
    gamelog = import_gamelog()
    with pytest.raises(ValueError):
        gamelog.parse_log(build())


# --- Stream grammar (SPEC 5.4) ----------------------------------------------

def test_empty_frame_worked_example_u_comma_comma_u_is_exactly_3_frames():
    """SPEC 5.4 worked example, asserted byte-exact in both directions."""
    gamelog = import_gamelog()
    frames = gamelog.parse_stream("u,,u\n")
    assert frames == ["u", "", "u"]
    assert len(frames) == 3
    assert gamelog.render_stream(["u", "", "u"]) == "u,,u\n"


def test_empty_stream_file_is_single_lf_and_zero_frames():
    gamelog = import_gamelog()
    assert gamelog.parse_stream("\n") == []
    assert gamelog.render_stream([]) == "\n"


def test_single_frame_stream_round_trips():
    gamelog = import_gamelog()
    assert gamelog.parse_stream("u\n") == ["u"]
    assert gamelog.render_stream(["u"]) == "u\n"


def test_n_frames_have_n_minus_1_commas_round_trip():
    gamelog = import_gamelog()
    text = expected_stream_text([("fire", 1), ("turn-left", 2)])
    frames = gamelog.parse_stream(text)
    assert len(frames) == 28
    assert text.count(",") == 27
    assert gamelog.render_stream(frames) == text


def test_multi_key_frames_accept_canonical_su_and_reject_us():
    gamelog = import_gamelog()
    assert gamelog.parse_stream("su,su\n") == ["su", "su"]
    with pytest.raises(ValueError):
        gamelog.parse_stream("us\n")
    with pytest.raises(ValueError):
        gamelog.render_stream(["us"])


def test_grammar_alphabet_admits_strafe_and_digit_keys_but_never_e_or_x():
    gamelog = import_gamelog()
    assert gamelog.parse_stream("0<,>\n") == ["0<", ">"]
    for bad in ("e\n", "x\n", "ex\n", "u,e\n"):
        with pytest.raises(ValueError):
            gamelog.parse_stream(bad)
    with pytest.raises(ValueError):
        gamelog.render_stream(["e"])


@pytest.mark.parametrize(
    ("case_id", "text"),
    [
        ("comma-before-final-lf", "u,\n"),
        ("no-trailing-lf", "u,u"),
        ("two-trailing-lfs", "u\n\n"),
        ("interior-lf", "u\nu\n"),
        ("crlf", "u\r\n"),
        ("duplicate-key-in-frame", "uu\n"),
        ("space-in-frame", "u u\n"),
        ("empty-file-no-lf", ""),
    ],
    ids=lambda v: v if (isinstance(v, str) and "\n" not in v and v) else None,
)
def test_invalid_stream_text_raises_value_error(case_id, text):
    gamelog = import_gamelog()
    with pytest.raises(ValueError):
        gamelog.parse_stream(text)


def test_unrepresentable_frame_lists_are_refused_on_render():
    """[""] and trailing-empty collide byte-wise with the empty-file and
    no-trailing-separator rules -- render must refuse, not silently alias."""
    gamelog = import_gamelog()
    with pytest.raises(ValueError):
        gamelog.render_stream([""])
    with pytest.raises(ValueError):
        gamelog.render_stream(["u", ""])


# --- The D13 invariant: stream == expand(ledger, mapping_version) -----------

def test_stream_equals_expand_of_ledger_byte_exact(tmp_path):
    """must_have 2 / RFC D13: the committed stream is regenerable from the
    ledger; the SPEC 5.4 worked example is the pinned observable, including the
    literal spelled out in SPEC ("f" x8 then "l" x20, 28 frames / 27 commas)."""
    from conftest import MAPPING_PATH
    section = make_section_text([
        ledger_line("2026-07-30T14:02:11Z", "alice", "fire", 1, 1),
        ledger_line("2026-07-30T14:03:00Z", "bob", "turn-left", 2, 2),
    ])
    path = tmp_path / "section.txt"
    path.write_text(section, encoding="ascii")
    proc = run_script("expand.py", ["--mapping", str(MAPPING_PATH), "--ledger", str(path)])
    assert proc.returncode == 0, proc.stderr
    stream = proc.stdout.decode("ascii")
    spec_literal = "f,f,f,f,f,f,f,f,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l\n"
    assert stream == spec_literal
    assert stream == expected_stream_text([("fire", 1), ("turn-left", 2)])
    gamelog = import_gamelog()
    assert gamelog.render_stream(gamelog.parse_stream(stream)) == stream
