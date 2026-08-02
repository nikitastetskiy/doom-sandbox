"""
@spec-handoff
@interface Control-table self-consistency (plan must_have 1): every
    issues/new?title= link inside the profile README's DOOM marker block, and
    every link rendered by rewrite_readme.py --controls-enabled, URL-decodes to
    a title accepted by game/scripts/parse_title.py
@behavior
    - README.md (repo root) carries the marker block with exactly the 12
      mapping control_links, each parsing to a valid token (red until E6 lands
      the block — that is this test's expected pre-E6 failure mode)
    - The rewriter's rendered output is self-consistent by construction:
      12/12 rendered links parse; the rendered title list equals the mapping's
      control_links in order
@edge-cases
    - Links are extracted by URL query parsing of the title param (%-decoding,
      %20 spaces), never by regex over prose outside the markers
@see game/SPEC.md section 9; game/mapping/v1.json control_links; RFC must_have 1
"""

import re
import urllib.parse

import pytest

from conftest import (
    CONTROL_LINKS,
    MARKER_END_B,
    MARKER_START_B,
    README_PATH,
    inside_block_bytes,
    json_stdout,
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


def test_readme_game_block_control_links_all_parse_against_the_whitelist(tmp_path):
    """must_have 1 regression guard over the real profile README.

    Expected red until plan step E6 merges the marker block; once the block
    exists, every prefilled title must parse and match the 12-link set.
    """
    data = README_PATH.read_bytes()
    if MARKER_START_B not in data or MARKER_END_B not in data:
        pytest.fail(
            "README.md has no DOOM marker block yet — expected red until plan "
            "step E6 lands the game block (this is the E3-documented failure mode)"
        )
    block = inside_block_bytes(data).decode("utf-8")
    titles = extract_link_titles(block)
    assert len(titles) == 12
    assert titles == CONTROL_LINKS
    for title in titles:
        proc = run_parser(title, tmp_path=tmp_path, transport="json")
        assert proc.returncode == 0, f"README control link title failed the parser: {title!r}"
        assert json_stdout(proc)["ok"] is True


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
