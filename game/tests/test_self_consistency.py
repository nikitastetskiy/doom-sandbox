"""
@spec-handoff
@interface Control-table self-consistency (plan must_have 1): every
    issues/new?title= link inside the profile README's DOOM marker block, and
    every link rendered by rewrite_readme.py --controls-enabled, URL-decodes to
    a title accepted by game/scripts/parse_title.py
@behavior
    - The real README.md (repo root) is checked in whichever cutover stage it
      is currently in (plan D5 / E9), and the stage is DETECTED, never assumed:
      * disabled stage (E9 stage 1, the committed state through the cutover
        window): the block shows the mapping's controls_disabled_placeholder
        byte-for-byte and carries ZERO issues/new?title= links
      * enabled stage (E9 stage 2 onward): the block carries exactly the 12
        mapping control_links, in order, each parsing to a valid token
    - must_have 1 is guarded in BOTH stages: regardless of the committed stage,
      the enabled-mode render OF THE REAL README (throwaway copy, via
      rewrite_readme.py --controls-enabled) must yield the 12 control_links and
      every one of them must parse. The disabled stage is therefore never a
      no-op — it asserts the placeholder contract AND the full enabled render
    - The rewriter's rendered output is self-consistent by construction:
      12/12 rendered links parse; the rendered title list equals the mapping's
      control_links in order
@edge-cases
    - Links are extracted by URL query parsing of the title param (%-decoding,
      %20 spaces), never by regex over prose outside the markers
    - A README with markers but neither placeholder nor links is a FAILURE
      (corrupt/hand-edited block), not a third tolerated stage
@see game/SPEC.md section 9; game/mapping/v1.json control_links; RFC must_have 1;
    plan D5 and E9 tasks 1-2 (disabled at merge, enabled at stage 2)
"""

import re
import urllib.parse

from conftest import (
    CONTROL_LINKS,
    MARKER_END_B,
    MARKER_START_B,
    README_PATH,
    inside_block_bytes,
    json_stdout,
    load_mapping,
    make_readme_bytes,
    run_parser,
    run_rewriter,
)

LINK_RE = re.compile(
    r"https://github\.com/nikitastetskiy/nikitastetskiy/issues/new\?[^)\s\"'<]+"
)


def extract_link_titles(block_text: str):
    titles = []
    for url in LINK_RE.findall(block_text):
        query = urllib.parse.urlsplit(url).query
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        assert "title" in params, f"control link without title param: {url}"
        titles.append(params["title"][0])
    return titles


def assert_all_titles_parse(titles, tmp_path, *, source):
    for title in titles:
        proc = run_parser(title, tmp_path=tmp_path, transport="json")
        assert proc.returncode == 0, (
            f"{source} control link title failed the whitelist parser: {title!r}"
        )
        assert json_stdout(proc)["ok"] is True


def test_readme_game_block_is_self_consistent_in_its_current_cutover_stage(tmp_path):
    """must_have 1 regression guard over the real profile README.

    The committed block is DISABLED mode from E6 through E9 stage 1 (plan D5)
    and ENABLED from E9 stage 2 onward. The stage is detected from the block
    itself, so this guard is satisfiable in both — and in both it also proves
    the enabled-mode render of this very README is fully parseable, so
    must_have 1 never goes unguarded during the disabled window.
    """
    data = README_PATH.read_bytes()
    assert MARKER_START_B in data and MARKER_END_B in data, (
        "README.md carries no DOOM marker block — the game block is missing "
        "from the profile README (landed in plan step E6)"
    )
    block = inside_block_bytes(data).decode("utf-8")
    placeholder = load_mapping()["controls_disabled_placeholder"]
    titles = extract_link_titles(block)

    if placeholder in block:
        # E9 stage 1: controls deliberately not yet advertised.
        assert titles == [], (
            "README block shows the disabled-controls placeholder but still "
            f"carries control links {titles} — disabled mode must render zero "
            "issues/new?title= links (plan D5)"
        )
    else:
        # E9 stage 2 onward: controls live on the profile.
        assert titles == CONTROL_LINKS, (
            f"README block control links {titles} do not match the mapping's "
            f"control_links {CONTROL_LINKS} (order-sensitive)"
        )
        assert_all_titles_parse(titles, tmp_path, source="README")

    # Guarded in BOTH stages: the enabled render of THIS README must be
    # self-consistent, so the disabled branch is never a no-op.
    working_copy = tmp_path / "README.md"
    working_copy.write_bytes(data)
    proc = run_rewriter(
        working_copy, state="PAUSED",
        image_url="https://example.com/doom.gif?run=selfcheck", controls_enabled=True,
    )
    assert proc.returncode == 0, (
        f"enabled-mode render of the real README failed: {proc.stdout!r} {proc.stderr!r}"
    )
    rendered = inside_block_bytes(working_copy.read_bytes()).decode("utf-8")
    rendered_titles = extract_link_titles(rendered)
    assert rendered_titles == CONTROL_LINKS, (
        f"enabled-mode render of the real README yields {rendered_titles}, "
        f"expected the mapping's control_links {CONTROL_LINKS}"
    )
    assert_all_titles_parse(rendered_titles, tmp_path, source="enabled-mode render of README")


def test_disabled_stage_placeholder_is_byte_exact_when_controls_are_off():
    """While the committed block is in disabled mode, the placeholder must be
    the mapping's literal — not paraphrased prose that merely omits links."""
    data = README_PATH.read_bytes()
    block = inside_block_bytes(data).decode("utf-8")
    placeholder = load_mapping()["controls_disabled_placeholder"]
    if placeholder in block:
        assert extract_link_titles(block) == []
        return
    # Enabled stage: assert we are genuinely enabled, not silently neither.
    assert extract_link_titles(block) == CONTROL_LINKS, (
        "README block is in neither cutover stage: it carries neither the exact "
        f"controls_disabled_placeholder {placeholder!r} nor the 12 control links "
        "— the block looks corrupt or hand-edited"
    )


def test_rendered_control_table_is_self_consistent_by_construction(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_bytes(make_readme_bytes())
    proc = run_rewriter(
        readme, state="LIVE",
        image_url="https://example.com/doom.gif?run=1", controls_enabled=True,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    block = inside_block_bytes(readme.read_bytes()).decode("utf-8")
    titles = extract_link_titles(block)
    assert len(titles) == 12
    for title in titles:
        parsed = run_parser(title, tmp_path=tmp_path, transport="json")
        assert parsed.returncode == 0, f"rendered link title failed the parser: {title!r}"
        out = json_stdout(parsed)
        assert out["ok"] is True and out["count"] >= 1


def test_rendered_titles_equal_the_mapping_control_links_in_order(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_bytes(make_readme_bytes())
    assert run_rewriter(
        readme, state="PAUSED",
        image_url="https://example.com/paused.png", controls_enabled=True,
    ).returncode == 0
    block = inside_block_bytes(readme.read_bytes()).decode("utf-8")
    assert extract_link_titles(block) == CONTROL_LINKS
