"""
@spec-handoff
@interface rewrite_readme.py --readme PATH --mapping PATH --state
    {LIVE,PAUSED,UNAVAILABLE,LOG_FULL} --image-url URL [--controls-enabled];
    exit 0 ok / 2 usage / 6 marker-validation failure; stdout JSON {"ok": true}
    or {"ok": false, "marker_error": missing-start|missing-end|duplicate-start|
    duplicate-end|reversed} (classes checked in that order, substring counts)
@behavior
    - Validates BEFORE writing: "<!-- DOOM:START -->" exactly once,
      "<!-- DOOM:END -->" exactly once, START before END; any violation ->
      exit 6 and the README file byte-untouched (fail-safe brick per RFC)
    - Rewrites ONLY the bytes strictly between the marker lines; marker lines
      and everything outside are byte-invariant (unicode/CRLF outside preserved
      verbatim); atomic replace (write temp then os.replace); idempotent:
      f(f(x)) == f(x) byte-identical; the block is a pure function of
      (mapping, state, image-url, flags), independent of the prior block
    - Block embeds --image-url verbatim with fixed alt text "DOOM (<STATE>)";
      controls enabled -> 3-column x 4-row markdown table of the mapping's 12
      control_links in order (row-major); href = https://github.com/
      nikitastetskiy/nikitastetskiy/issues/new?title=<RFC3986 %-encoded title,
      %20 for space>&body=Just%20press%20Submit%20%E2%80%94%20your%20move%20
      runs%20automatically. ; label = mapping token label (+ " x<n>" on repeat
      variants); controls disabled -> the mapping's controls_disabled_placeholder
      line exactly, zero issues/new?title= links
@edge-cases
    - Marker text quoted anywhere else in the file (prose or code fence) ->
      duplicate class -> abort untouched; missing final newline after the END
      marker region is preserved byte-exact
@see game/SPEC.md section 9; game/mapping/v1.json control_links; RFC must_have 8
"""

import urllib.parse

import pytest

from conftest import (
    CONTROL_LINKS,
    CONTROL_TABLE_COLUMNS,
    CONTROL_TABLE_ROWS,
    ISSUE_BODY_PARAM,
    ISSUE_URL_PREFIX,
    MARKER_END_B,
    MARKER_START_B,
    TOKENS,
    inside_block_bytes,
    json_stdout,
    load_mapping,
    make_readme_bytes,
    outside_parts_bytes,
    run_rewriter,
)

GIF_URL = "https://raw.githubusercontent.com/nikitastetskiy/nikitastetskiy/output/doom.gif?run=12345"


def write_readme(tmp_path, data: bytes, name="README.md"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- Marker-pair validation abort classes -----------------------------------

def _strip_marker(data: bytes, marker: bytes) -> bytes:
    return data.replace(marker, b"<!-- gone -->")


ABORT_CASES = [
    ("missing-start", lambda d: _strip_marker(d, MARKER_START_B), "missing-start"),
    ("missing-end", lambda d: _strip_marker(d, MARKER_END_B), "missing-end"),
    ("duplicate-start", lambda d: d + b"\nquoted: " + MARKER_START_B + b"\n", "duplicate-start"),
    ("duplicate-end", lambda d: MARKER_END_B + b" stray\n" + d, "duplicate-end"),
    (
        "reversed-order",
        lambda d: d.replace(MARKER_START_B, b"@@TMP@@")
                   .replace(MARKER_END_B, MARKER_START_B)
                   .replace(b"@@TMP@@", MARKER_END_B),
        "reversed",
    ),
    ("both-missing", lambda d: _strip_marker(_strip_marker(d, MARKER_START_B), MARKER_END_B),
     "missing-start"),
]


@pytest.mark.parametrize(
    ("mutate", "marker_error"),
    [(m, e) for _, m, e in ABORT_CASES],
    ids=[i for i, _, _ in ABORT_CASES],
)
def test_marker_validation_failure_aborts_without_touching_the_file(tmp_path, mutate, marker_error):
    data = mutate(make_readme_bytes())
    path = write_readme(tmp_path, data)
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL)
    assert proc.returncode == 6, (proc.stdout, proc.stderr)
    out = json_stdout(proc)
    assert out["ok"] is False
    assert out["marker_error"] == marker_error
    assert path.read_bytes() == data, "abort must leave the README byte-untouched"


def test_marker_quoted_in_a_code_fence_counts_as_duplicate_and_aborts(tmp_path):
    data = make_readme_bytes() + (
        b"\n```\nexample: " + MARKER_START_B + b"\n```\n"
    )
    path = write_readme(tmp_path, data)
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL)
    assert proc.returncode == 6
    assert json_stdout(proc)["marker_error"] == "duplicate-start"
    assert path.read_bytes() == data


def test_missing_readme_file_is_a_usage_error(tmp_path):
    proc = run_rewriter(tmp_path / "absent.md", state="LIVE", image_url=GIF_URL)
    assert proc.returncode == 2


# --- Successful rewrite: isolation and idempotence --------------------------

def test_rewrite_changes_only_bytes_between_the_marker_lines(tmp_path):
    original = make_readme_bytes()
    path = write_readme(tmp_path, original)
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    rewritten = path.read_bytes()
    assert outside_parts_bytes(rewritten) == outside_parts_bytes(original)
    assert rewritten.count(MARKER_START_B) == 1
    assert rewritten.count(MARKER_END_B) == 1
    assert GIF_URL.encode() in inside_block_bytes(rewritten)
    assert GIF_URL.encode() not in outside_parts_bytes(rewritten)[0]
    assert GIF_URL.encode() not in outside_parts_bytes(rewritten)[1]


def test_rewrite_is_idempotent_f_of_f_equals_f(tmp_path):
    """must_have 8: applying the rewrite twice with identical inputs yields a
    byte-identical README."""
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True).returncode == 0
    first = path.read_bytes()
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True).returncode == 0
    second = path.read_bytes()
    assert second == first


def test_block_content_is_a_pure_function_of_inputs_not_prior_block(tmp_path):
    a = write_readme(tmp_path, make_readme_bytes(block=b"old block A\n"), name="a.md")
    b = write_readme(tmp_path, make_readme_bytes(block=b"completely different B\n"), name="b.md")
    assert run_rewriter(a, state="PAUSED", image_url=GIF_URL).returncode == 0
    assert run_rewriter(b, state="PAUSED", image_url=GIF_URL).returncode == 0
    assert inside_block_bytes(a.read_bytes()) == inside_block_bytes(b.read_bytes())


def test_state_screen_swap_rewrites_only_inside_markers(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL).returncode == 0
    live = path.read_bytes()
    assert run_rewriter(
        path, state="UNAVAILABLE", image_url="https://example.com/unavailable.png"
    ).returncode == 0
    unavailable = path.read_bytes()
    assert outside_parts_bytes(unavailable) == outside_parts_bytes(live)
    assert inside_block_bytes(unavailable) != inside_block_bytes(live)
    assert b"DOOM (UNAVAILABLE)" in inside_block_bytes(unavailable)
    assert b"DOOM (LIVE)" in inside_block_bytes(live)


@pytest.mark.parametrize("state", ["LIVE", "PAUSED", "UNAVAILABLE", "LOG_FULL"])
def test_every_state_renders_with_fixed_alt_text(tmp_path, state):
    path = write_readme(tmp_path, make_readme_bytes())
    proc = run_rewriter(path, state=state, image_url="https://example.com/s.png")
    assert proc.returncode == 0
    assert f"DOOM ({state})".encode() in inside_block_bytes(path.read_bytes())


def test_unicode_and_crlf_outside_markers_survive_byte_exact(tmp_path):
    prefix = "# Ník — プロフィール 🚀\r\nCRLF line\r\n\n".encode("utf-8")
    suffix = "\ntrailing — ünïcödé\r\nend".encode("utf-8")  # no final newline
    original = make_readme_bytes(prefix=prefix, suffix=suffix)
    path = write_readme(tmp_path, original)
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL).returncode == 0
    rewritten = path.read_bytes()
    # Byte-exact on the whole outside region, marker lines included.
    assert outside_parts_bytes(rewritten) == outside_parts_bytes(original)
    # ...and the payloads themselves survive verbatim: no unicode normalization,
    # no CRLF->LF rewriting, no re-encoding of the surrounding profile content.
    out_prefix, out_suffix = outside_parts_bytes(rewritten)
    assert out_prefix.startswith(prefix), "unicode/CRLF prefix payload was altered"
    assert out_suffix.endswith(suffix), "unicode/CRLF suffix payload was altered"
    assert rewritten.count(prefix) == 1 and rewritten.count(suffix) == 1


# --- Control-table rendering (SPEC section 9, plan D5) ----------------------

def expected_href(title: str) -> str:
    return ISSUE_URL_PREFIX + urllib.parse.quote(title, safe="") + "&body=" + ISSUE_BODY_PARAM


def expected_label(title: str) -> str:
    mapping = load_mapping()
    by_title = {t["title"]: t["label"] for t in mapping["tokens"]}
    if title in by_title:
        return by_title[title]
    base, _, suffix = title.rpartition(" x")
    return f"{by_title[base]} x{suffix}"


def test_enabled_control_table_renders_all_12_links_in_spec_order(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL, controls_enabled=True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    hrefs = [expected_href(t) for t in CONTROL_LINKS]
    positions = []
    for href in hrefs:
        assert href in block, f"missing control link for {href}"
        positions.append(block.index(href))
    assert positions == sorted(positions), "links must appear in SPEC section 9 order"
    assert block.count(ISSUE_URL_PREFIX) == 12


def test_enabled_control_table_is_3_columns_by_4_rows(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True).returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    link_rows = [
        line for line in block.splitlines()
        if ISSUE_URL_PREFIX in line
    ]
    assert len(link_rows) == CONTROL_TABLE_ROWS
    for row in link_rows:
        assert row.count(ISSUE_URL_PREFIX) == CONTROL_TABLE_COLUMNS


def test_control_labels_come_from_the_mapping_including_repeat_suffix(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True).returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    for title in CONTROL_LINKS:
        assert expected_label(title) in block
    assert expected_label("doom: forward x5").endswith(" x5")


def test_every_control_link_carries_the_fixed_body_param(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True).returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    assert block.count("&body=" + ISSUE_BODY_PARAM) == 12


def test_disabled_controls_render_the_exact_placeholder_and_no_links(tmp_path):
    mapping = load_mapping()
    placeholder = mapping["controls_disabled_placeholder"]
    assert "Controls are being wired up" in placeholder
    assert placeholder.endswith("the arcade opens soon.")
    path = write_readme(tmp_path, make_readme_bytes())
    proc = run_rewriter(path, state="PAUSED", image_url=GIF_URL, controls_enabled=False)
    assert proc.returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    assert placeholder in block
    assert ISSUE_URL_PREFIX not in block
    assert "issues/new?title=" not in block


def test_mapping_control_links_array_matches_spec_section_9(tmp_path):
    """VERBATIM consumption check for the 12-link list (rides with a script
    call so it stays red until E4)."""
    mapping = load_mapping()
    assert mapping["control_links"] == CONTROL_LINKS
    canonical = {t["title"] for t in mapping["tokens"]}
    for title in CONTROL_LINKS:
        base = title.rpartition(" x")[0] if " x" in title else title
        assert title in mapping["canonical_titles"]
        assert base in canonical or title in canonical
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL).returncode == 0
