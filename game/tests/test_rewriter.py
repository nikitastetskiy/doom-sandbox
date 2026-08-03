"""
@spec-handoff
@interface rewrite_readme.py --readme PATH --mapping PATH --state
    {LIVE,PAUSED,UNAVAILABLE,LOG_FULL,SEALED} --image-url URL
    [--controls-enabled --repository OWNER/NAME];
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
      control_links in order (row-major); href = https://github.com/<the
      --repository value>/issues/new?title=<RFC3986 %-encoded title, %20 for
      space>&body=Just%20press%20Submit%20%E2%80%94%20your%20move%20
      runs%20automatically. ; label = mapping token label (+ " x<n>" on repeat
      variants); controls disabled -> the mapping's controls_disabled_placeholder
      line exactly, zero issues/new?title= links
    - AMENDMENT (SPEC 9.1): NEW ARGUMENT --repository OWNER/NAME, the
      control-link target, supplied by the workflow from GITHUB_REPOSITORY.
      Required IF AND ONLY IF --controls-enabled; NO default and NO fallback,
      and no repository may remain as a literal in the module (the current
      ISSUE_NEW_URL constant is the defect). Rendering the table without it is
      exit 2, README byte-untouched. The value is validated as an anchored
      ASCII full match against
      \\A[A-Za-z0-9][A-Za-z0-9._-]{0,38}/[A-Za-z0-9._-]{1,100}\\z and then
      interpolated into the URL path UNESCAPED, because the `/` is structural.
      That is sound only because the grammar admits no character special in a
      URL (? # & % : @ space) or a Markdown link target (( ) < > " ` \\ space) —
      the validation IS the escaping strategy, not a courtesy check. A reject
      is exit 2 with the README untouched
@edge-cases
    - Marker text quoted anywhere else in the file (prose or code fence) ->
      duplicate class -> abort untouched; missing final newline after the END
      marker region is preserved byte-exact
    - SEALED is the SPEC §11 guidance screen shown while the current section is
      sealed by a pin mismatch (§5.5). It is distinct from UNAVAILABLE (moves
      ARE being processed) and from LOG_FULL (the section is not full — its
      toolchain moved), and needs its own screen asset, parallel to LOG_FULL
@see game/SPEC.md sections 9 and 11; §5.5 (sealed sections);
    game/mapping/v1.json control_links; RFC must_have 8
"""

import urllib.parse

import pytest

from conftest import (
    CONTROL_LINKS,
    CONTROL_TABLE_COLUMNS,
    CONTROL_TABLE_ROWS,
    ISSUE_BODY_PARAM,
    OTHER_TEST_REPOSITORY,
    SCRIPTS_DIR,
    TEST_REPOSITORY,
    issue_url_prefix,
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
                        controls_enabled=True, repository=TEST_REPOSITORY).returncode == 0
    first = path.read_bytes()
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=TEST_REPOSITORY).returncode == 0
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


@pytest.mark.parametrize("state", ["LIVE", "PAUSED", "UNAVAILABLE", "LOG_FULL", "SEALED"])
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
    return issue_url_prefix(TEST_REPOSITORY) + urllib.parse.quote(title, safe="") + "&body=" + ISSUE_BODY_PARAM


def expected_label(title: str) -> str:
    mapping = load_mapping()
    by_title = {t["title"]: t["label"] for t in mapping["tokens"]}
    if title in by_title:
        return by_title[title]
    base, _, suffix = title.rpartition(" x")
    return f"{by_title[base]} x{suffix}"


def test_enabled_control_table_renders_all_12_links_in_spec_order(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL, controls_enabled=True, repository=TEST_REPOSITORY)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    hrefs = [expected_href(t) for t in CONTROL_LINKS]
    positions = []
    for href in hrefs:
        assert href in block, f"missing control link for {href}"
        positions.append(block.index(href))
    assert positions == sorted(positions), "links must appear in SPEC section 9 order"
    assert block.count(issue_url_prefix(TEST_REPOSITORY)) == 12


def test_enabled_control_table_is_3_columns_by_4_rows(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=TEST_REPOSITORY).returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    link_rows = [
        line for line in block.splitlines()
        if issue_url_prefix(TEST_REPOSITORY) in line
    ]
    assert len(link_rows) == CONTROL_TABLE_ROWS
    for row in link_rows:
        assert row.count(issue_url_prefix(TEST_REPOSITORY)) == CONTROL_TABLE_COLUMNS


def test_control_labels_come_from_the_mapping_including_repeat_suffix(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=TEST_REPOSITORY).returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    for title in CONTROL_LINKS:
        assert expected_label(title) in block
    assert expected_label("doom: forward x5").endswith(" x5")


def test_every_control_link_carries_the_fixed_body_param(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=TEST_REPOSITORY).returncode == 0
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
    assert issue_url_prefix(TEST_REPOSITORY) not in block
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


# --- SPEC 9.1: the control-link target ---------------------------------------
#
# The motivating instance: the renderer carried the profile repository as a
# module constant, so when the rehearsal sandbox rendered the block, 12 of 12
# links pointed at the profile — a click would have filed a stranger's move on
# a repository whose workflow the sandbox never runs. A boundary violation and
# a dead control, from one correct-looking literal.

def test_the_control_table_cannot_be_rendered_without_a_target(tmp_path):
    """No default, no fallback: a default is indistinguishable from a hardcode
    at the exact moment it matters — the first deployment that is not the one
    the default names."""
    path = write_readme(tmp_path, make_readme_bytes())
    before = path.read_bytes()
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=None)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert path.read_bytes() == before, "the README must be byte-untouched"


def test_a_target_is_not_required_when_the_control_table_is_not_rendered(tmp_path):
    """Required if and only if the table is rendered: with --controls-enabled
    absent the placeholder line is rendered, there is no link, and there is
    nothing to target."""
    path = write_readme(tmp_path, make_readme_bytes())
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=False, repository=None)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    assert "issues/new?title=" not in block, block


def test_the_rendered_links_target_the_repository_supplied(tmp_path):
    path = write_readme(tmp_path, make_readme_bytes())
    assert run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True,
                        repository=OTHER_TEST_REPOSITORY).returncode == 0
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    assert block.count(issue_url_prefix(OTHER_TEST_REPOSITORY)) == 12, block
    assert issue_url_prefix(TEST_REPOSITORY) not in block, (
        "a second target leaked into the render"
    )


def test_no_repository_is_baked_into_the_renderer_source():
    """The residual SPEC 9.1 closes by SOURCE rather than by predicate: an
    authored literal passes the grammar exactly as readily as the correct
    value, so 'where the value comes from' is normative."""
    source = (SCRIPTS_DIR / "rewrite_readme.py").read_text(encoding="utf-8")
    offenders = [
        line.strip() for line in source.splitlines()
        if "github.com/" in line and "issues/new" in line and "{" not in line
        and not line.strip().startswith("#")
    ]
    assert offenders == [], (
        f"rewrite_readme.py authors a control-link URL with a literal target: "
        f"{offenders}"
    )


# SPEC 9.1, verbatim: \A[A-Za-z0-9][A-Za-z0-9._-]{0,38}/[A-Za-z0-9._-]{1,100}\z
VALID_TARGETS = {
    "minimal": "a/b",
    "digits-only": "0/9",
    "dots-in-name": "owner/name.with.dots",
    "hyphens-in-name": "owner/name-with-hyphens",
    "underscores-in-name": "owner/name_with_underscores",
    "hyphen-inside-owner": "an-owner/a-name",
    "owner-at-39-chars": "a" * 39 + "/name",
    "name-at-100-chars": "owner/" + "n" * 100,
}

INVALID_TARGETS = {
    # Shape
    "no-separator": "ownername",
    "two-separators": "owner/name/extra",
    "empty-owner": "/name",
    "empty-name": "owner/",
    "owner-starts-with-hyphen": "-owner/name",
    "owner-starts-with-dot": ".owner/name",
    "owner-at-40-chars": "a" * 40 + "/name",
    "name-at-101-chars": "owner/" + "n" * 101,
    # Characters special in a URL — the grammar admits none of them, which is
    # the ENTIRE reason the value may be interpolated unescaped.
    "question-mark": "owner/na?me",
    "hash": "owner/na#me",
    "ampersand": "owner/na&me",
    "percent": "owner/na%20me",
    "colon": "owner/na:me",
    "at-sign": "owner/na@me",
    "space": "owner/na me",
    # Characters special in a Markdown link target
    "close-paren": "owner/na)me",
    "open-paren": "owner/na(me",
    "angle-brackets": "owner/na<me>",
    "double-quote": 'owner/na"me',
    "backtick": "owner/na`me",
    "backslash": "owner/na\\me",
    # Injection shapes
    "newline": "owner/name\nowner2/name2",
    "full-url": "https://github.com/owner/name",
    "leading-slash": "/owner/name",
    "non-ascii": "ówner/name",
}


@pytest.mark.parametrize("target", VALID_TARGETS.values(), ids=list(VALID_TARGETS))
def test_a_target_inside_the_grammar_is_accepted(tmp_path, target):
    path = write_readme(tmp_path, make_readme_bytes())
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=target)
    assert proc.returncode == 0, (target, proc.stdout, proc.stderr)
    block = inside_block_bytes(path.read_bytes()).decode("utf-8")
    assert block.count(issue_url_prefix(target)) == 12, block


@pytest.fixture(scope="module")
def repository_probe(tmp_path_factory):
    """One render with a KNOWN-GOOD target, shared by every reject test."""
    path = write_readme(tmp_path_factory.mktemp("probe"), make_readme_bytes())
    return run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=TEST_REPOSITORY)


def assert_the_grammar_is_what_rejects(probe):
    """Guard against a false green on every reject test below.

    While `--repository` is unrecognized argparse exits 2 for EVERY value, so a
    reject test passes without the SPEC 9.1 grammar existing at all — the right
    answer for the wrong reason. Requiring a VALID target to succeed first
    makes those tests report the grammar and nothing else.
    """
    assert probe.returncode == 0, (
        "rewrite_readme.py does not accept --repository, so every reject here "
        "would pass on argparse's exit 2 rather than on the SPEC 9.1 grammar: "
        f"{probe.stderr!r}"
    )


@pytest.mark.parametrize("target", INVALID_TARGETS.values(), ids=list(INVALID_TARGETS))
def test_a_target_outside_the_grammar_is_a_usage_error(tmp_path, target,
                                                       repository_probe):
    """The validation is not a courtesy check — it is the entire escaping
    strategy, and may not be relaxed without replacing it."""
    assert_the_grammar_is_what_rejects(repository_probe)
    path = write_readme(tmp_path, make_readme_bytes())
    before = path.read_bytes()
    proc = run_rewriter(path, state="LIVE", image_url=GIF_URL,
                        controls_enabled=True, repository=target)
    assert proc.returncode == 2, (target, proc.returncode, proc.stdout, proc.stderr)
    assert path.read_bytes() == before, f"README was touched on reject: {target!r}"


def test_the_grammar_is_anchored_at_both_ends(tmp_path, repository_probe):
    """An unanchored match would admit a valid target with arbitrary bytes
    attached, which is the one way an unescaped interpolation can escape."""
    assert_the_grammar_is_what_rejects(repository_probe)
    path = write_readme(tmp_path, make_readme_bytes())
    for target in ("owner/name)](https://evil.example)", "owner/name?x=1",
                   "prefix owner/name", "owner/name suffix"):
        before = path.read_bytes()
        proc = run_rewriter(path, state="LIVE", image_url=GIF_URL,
                            controls_enabled=True, repository=target)
        assert proc.returncode == 2, (target, proc.stdout, proc.stderr)
        assert path.read_bytes() == before, target
