"""
@spec-handoff
@interface NONE — this file has no implementation target. It is a checked-in
    regression guard over two artifacts that already exist: game/SPEC.md (E1,
    human-normative) and game/mapping/v1.json (E1, machine-readable mirror).
    Unlike the rest of game/tests/, it is expected GREEN on write and must be
    kept out of the E3 red-run evidence.
@behavior
    - SPEC.md is parsed as the SOURCE OF TRUTH and compared field-by-field to
      the mapping; no expected value is hardcoded here (hardcoding would only
      relocate the drift into the test). The only literals below are structural
      LINKAGE patterns — which SPEC row/prose sentence backs which mapping key
    - Covers every normative block: tokens (id, title literal, keys, frames,
      repeatable, label), key hygiene (no e/x, ASCII-ascending order), repeat
      bounds, the canonical title set REGENERATED from SPEC's generation rule
      and set-compared, grammar accept/reject equivalence against SPEC's own
      informative regex, control links (order-sensitive), the disabled
      placeholder literal, all 9 knobs, the 4 latency values, and the budget
      block (ceiling + every ladder rung field + monotonicity)
    - Test IDs are field paths and every message is prefixed "DRIFT [<field>]",
      so the CI check Rin wires in E5 names the drifted field directly
@edge-cases
    - A SPEC extraction that matches nothing FAILS loudly (never skips, never
      passes vacuously) — an unparseable SPEC is itself a drift signal
    - Existence is symmetric: a key added to the mapping without a SPEC row
      fails, and a SPEC row with no mapping key fails
@see game/SPEC.md; game/mapping/v1.json; plan step E3 task 4 (guards the
    E1/E2 ladder drift class fixed in 6e85fe5)
"""

import functools
import json
import re

import pytest

from conftest import GAME_DIR, MAPPING_PATH, V1_EXPANSION_ALPHABET

SPEC_PATH = GAME_DIR / "SPEC.md"

# --- Structural linkage only: which SPEC row backs which mapping knob key.
# These are NOT expected values — every value is extracted from SPEC at runtime.
KNOB_ROW_PATTERNS = {
    "new_game_cooldown_minutes": r"^`new game` cooldown",
    "per_user_move_cooldown_minutes": r"^Per-user move cooldown",
    "drain_cap_issues_per_run": r"^Per-run drain cap",
    "section_cap_frames": r"^Log-section cap",
    "push_retry_attempts": r"^Push retry attempts",
    "sweep_cron": r"^Sweep cron",
    "sweep_owner_alert_consecutive_failures": r"^Sweep owner-alert threshold",
    "abuse_trailing_24h_run_threshold": r"^Trailing-24h abuse run-count threshold",
    "title_byte_cap": r"^Title byte cap",
    "idle_pause_days": r"^Idle-to-PAUSED threshold",
}

# Structural linkage for the SPEC section 7 latency prose -> mapping key.
LATENCY_PATTERNS = {
    "trailing_window_moves": r"trailing \*\*(\d+) accepted moves\*\*()",
    "defect_p50_seconds": r"p50 > \*\*(\d+)\s*(minutes?|min|s|seconds?)\*\*",
    "target_seconds": r"Target < (\d+)\s*(minutes?|min|s|seconds?)",
    "stretch_p50_seconds": r"p50 < (\d+)\s*(minutes?|min|s|seconds?)",
}

TOKEN_FIELDS = ("title", "keys", "frames", "repeatable", "label")
LADDER_FIELDS = ("level", "tail_seconds", "width_px", "fps", "colors")


# --- Artifact loading --------------------------------------------------------

@functools.lru_cache(maxsize=1)
def spec_text():
    return SPEC_PATH.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def mapping():
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def extract(pattern, *, field, flags=0, group=1):
    """Pull a value out of SPEC.md, failing loudly if the prose no longer matches."""
    match = re.search(pattern, spec_text(), flags)
    assert match is not None, (
        f"DRIFT [{field}]: game/SPEC.md no longer states this value in the "
        f"expected form — pattern {pattern!r} matched nothing. An unparseable "
        f"SPEC is itself drift; fix SPEC.md or this linkage pattern."
    )
    return match.group(group)


def to_seconds(value, unit):
    return int(value) * (60 if unit.startswith("min") else 1)


def to_int(text):
    digits = re.search(r"-?[\d,]+", text)
    assert digits, f"no integer found in SPEC value cell {text!r}"
    return int(digits.group(0).replace(",", ""))


# --- SPEC section 1: token table --------------------------------------------

@functools.lru_cache(maxsize=1)
def spec_tokens():
    """Parse the section 1 token table into {id: {field: value}}."""
    tokens = {}
    for line in spec_text().splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line[1:-1].split("|")]
        if len(cells) != 7:
            continue
        id_match = re.fullmatch(r"`([a-z-]+)`", cells[0])
        if not id_match:
            continue
        keys_match = re.search(r"`([^`]*)`", cells[2])
        repeatable = cells[5].replace("*", "").strip()
        tokens[id_match.group(1)] = {
            "title": cells[1].strip("`"),
            # the new-game row states "— (0 frames)" rather than a backticked
            # key literal; absence of a key literal means "expands to nothing"
            "keys": keys_match.group(1) if keys_match else "",
            "frames": int(cells[3]),
            "repeatable": repeatable == "yes",
            "label": cells[6].strip(),
        }
    assert tokens, "DRIFT [tokens]: could not parse the SPEC.md section 1 token table"
    return tokens


@functools.lru_cache(maxsize=1)
def spec_repeat_bounds():
    text = extract(r"integer in \*\*\[(\d+,\s*\d+)\]\*\*", field="repeat")
    low, high = (int(p) for p in text.split(","))
    return low, high


def mapping_tokens():
    return {t["id"]: t for t in mapping()["tokens"]}


# --- Tokens -------------------------------------------------------------------

def test_token_id_sets_are_identical():
    spec_ids = set(spec_tokens())
    json_ids = set(mapping_tokens())
    assert json_ids == spec_ids, (
        f"DRIFT [tokens.ids]: only in mapping/v1.json={sorted(json_ids - spec_ids)}, "
        f"only in SPEC.md §1={sorted(spec_ids - json_ids)}"
    )


@pytest.mark.parametrize("token_id", sorted(spec_tokens()))
@pytest.mark.parametrize("field", TOKEN_FIELDS)
def test_token_field_matches_spec(token_id, field):
    spec_value = spec_tokens()[token_id][field]
    entry = mapping_tokens().get(token_id)
    assert entry is not None, f"DRIFT [tokens.{token_id}]: absent from mapping/v1.json"
    assert entry.get(field) == spec_value, (
        f"DRIFT [tokens.{token_id}.{field}]: mapping/v1.json has "
        f"{entry.get(field)!r} — game/SPEC.md §1 has {spec_value!r}"
    )


def test_new_game_is_a_zero_frame_reset_control_in_both_artifacts():
    spec_entry = spec_tokens()["new-game"]
    json_entry = mapping_tokens()["new-game"]
    assert spec_entry["frames"] == 0 and spec_entry["keys"] == ""
    assert json_entry["frames"] == 0 and json_entry["keys"] == "", (
        f"DRIFT [tokens.new-game]: mapping/v1.json frames={json_entry['frames']!r} "
        f"keys={json_entry['keys']!r} — SPEC.md §1 declares a zero-frame control"
    )
    assert json_entry.get("control") == "reset", (
        "DRIFT [tokens.new-game.control]: SPEC.md §1 calls new-game a ledger "
        f"control directive; mapping/v1.json has control={json_entry.get('control')!r}"
    )


# --- Key hygiene ---------------------------------------------------------------

@pytest.mark.parametrize("token_id", sorted(spec_tokens()))
def test_no_token_expands_to_menu_keys_e_or_x(token_id):
    keys = mapping_tokens()[token_id]["keys"]
    offenders = sorted(set(keys) & {"e", "x"})
    assert not offenders, (
        f"DRIFT [tokens.{token_id}.keys]: contains menu key(s) {offenders} — "
        "SPEC.md §1 declares e/x unexpandable by construction"
    )


@pytest.mark.parametrize("token_id", sorted(spec_tokens()))
def test_token_keys_are_within_the_v1_expansion_alphabet(token_id):
    keys = mapping_tokens()[token_id]["keys"]
    assert set(keys) <= V1_EXPANSION_ALPHABET, (
        f"DRIFT [tokens.{token_id}.keys]: {keys!r} leaves the v1 expansion "
        f"alphabet {sorted(V1_EXPANSION_ALPHABET)} (SPEC.md §5.4)"
    )


@pytest.mark.parametrize("token_id", sorted(spec_tokens()))
def test_token_keys_are_in_canonical_ascending_ascii_order(token_id):
    keys = mapping_tokens()[token_id]["keys"]
    assert list(keys) == sorted(keys), (
        f"DRIFT [tokens.{token_id}.keys]: {keys!r} is not ascending ASCII — "
        "SPEC.md §5.4 pins canonical multi-key order (su, never us)"
    )
    assert len(set(keys)) == len(keys), (
        f"DRIFT [tokens.{token_id}.keys]: {keys!r} repeats a key within one frame"
    )


# --- Repeat bounds --------------------------------------------------------------

@pytest.mark.parametrize("bound", ["min", "max"])
def test_repeat_bounds_match_spec(bound):
    low, high = spec_repeat_bounds()
    spec_value = low if bound == "min" else high
    json_value = mapping()["repeat"][bound]
    assert json_value == spec_value, (
        f"DRIFT [repeat.{bound}]: mapping/v1.json has {json_value} — "
        f"game/SPEC.md §2 states bounds [{low}, {high}]"
    )


# --- Canonical title set (regenerated from SPEC's generation rule) --------------

def regenerate_canonical_titles():
    """SPEC §3 rule: each token's literal, plus '<literal> x<n>' for every
    repeatable token over the SPEC repeat bounds."""
    low, high = spec_repeat_bounds()
    titles = []
    for spec_entry in spec_tokens().values():
        titles.append(spec_entry["title"])
        if spec_entry["repeatable"]:
            titles += [f"{spec_entry['title']} x{n}" for n in range(low, high + 1)]
    return titles


def test_canonical_titles_equal_the_regenerated_set():
    generated = regenerate_canonical_titles()
    listed = mapping()["canonical_titles"]
    assert set(listed) == set(generated), (
        "DRIFT [canonical_titles]: only in mapping/v1.json="
        f"{sorted(set(listed) - set(generated))}, only in the SPEC.md §3 "
        f"generation rule={sorted(set(generated) - set(listed))}"
    )


def test_canonical_title_count_matches_the_number_spec_states():
    stated = int(extract(r"=\s*\*\*(\d+) literals\*\*", field="canonical_titles.count"))
    listed = mapping()["canonical_titles"]
    assert len(listed) == stated, (
        f"DRIFT [canonical_titles.count]: mapping/v1.json lists {len(listed)} — "
        f"game/SPEC.md §3 states {stated}"
    )
    assert len(regenerate_canonical_titles()) == stated, (
        f"DRIFT [canonical_titles.count]: the SPEC.md §3 generation rule yields "
        f"{len(regenerate_canonical_titles())} but the same section states {stated}"
    )


def test_canonical_title_composition_matches_the_spec_arithmetic():
    """SPEC §3 spells out '<B> base literals + (<R> repeatable tokens x counts)'."""
    base = int(extract(r"=\s*(\d+) base literals", field="canonical_titles.base"))
    repeatable = int(
        extract(r"base literals \+ \((\d+) repeatable tokens", field="canonical_titles.repeatable")
    )
    assert len(spec_tokens()) == base, (
        f"DRIFT [tokens.count]: SPEC.md §1 table has {len(spec_tokens())} rows — "
        f"§3 arithmetic assumes {base} base literals"
    )
    json_repeatable = sum(1 for t in mapping()["tokens"] if t["repeatable"])
    assert json_repeatable == repeatable, (
        f"DRIFT [tokens.repeatable.count]: mapping/v1.json marks {json_repeatable} "
        f"tokens repeatable — game/SPEC.md §3 arithmetic assumes {repeatable}"
    )


def test_canonical_titles_are_unique_ascii_and_within_the_byte_cap():
    listed = mapping()["canonical_titles"]
    assert len(set(listed)) == len(listed), "DRIFT [canonical_titles]: contains duplicates"
    non_ascii = [t for t in listed if not t.isascii()]
    assert not non_ascii, (
        f"DRIFT [canonical_titles]: non-ASCII literals {non_ascii} — "
        "SPEC.md §4 bans non-ASCII from the grammar"
    )
    cap = to_int(spec_knob_cell("title_byte_cap"))
    too_long = [t for t in listed if len(t.encode("utf-8")) > cap]
    assert not too_long, (
        f"DRIFT [canonical_titles]: {too_long} exceed the SPEC.md §6 title byte cap {cap}"
    )


# --- Grammar equivalence against SPEC's own informative regex -------------------

@functools.lru_cache(maxsize=1)
def spec_grammar_regex():
    pattern = extract(
        r"\*\*Informative regex\*\*[^`]*`(.+?)`", field="grammar.regex", flags=re.S
    )
    # SPEC writes \z (Perl/Ruby end-of-string); Python spells it \Z
    return re.compile(pattern.replace(r"\z", r"\Z"))


def test_spec_regex_accepts_every_canonical_title():
    rejected = [t for t in mapping()["canonical_titles"] if not spec_grammar_regex().fullmatch(t)]
    assert not rejected, (
        f"DRIFT [grammar]: SPEC.md §3 informative regex rejects canonical "
        f"titles listed in mapping/v1.json: {rejected}"
    )


def near_miss_titles():
    """Reject-class samples built FROM the mapping — not hardcoded expectations."""
    low, high = spec_repeat_bounds()
    samples = ["doom:", "doom: ", ""]
    for entry in mapping()["tokens"]:
        title = entry["title"]
        samples += [
            f"{title} x{low - 1}",          # below the lower bound
            f"{title} x{high + 1}",         # above the upper bound
            f"{title} x0",
            f"{title} x0{low}",             # zero-padded
            f"{title} && rm -rf /",         # prefix + trailing garbage
            f"{title} ",                    # trailing space
            f" {title}",                    # leading space
            f"{title}x{low}",               # missing separator space
        ]
        if not entry["repeatable"]:
            samples.append(f"{title} x{low}")  # repeat on a non-repeatable token
    return sorted(set(samples) - set(mapping()["canonical_titles"]))


@pytest.mark.parametrize("title", near_miss_titles())
def test_spec_regex_rejects_near_misses_built_from_the_mapping(title):
    assert not spec_grammar_regex().fullmatch(title), (
        f"DRIFT [grammar]: SPEC.md §3 informative regex accepts {title!r}, "
        "which is not a canonical title in mapping/v1.json"
    )


def test_new_game_admits_no_repeat_suffix_in_either_artifact():
    """SPEC §2.1 exact-literal rule, cross-checked against the mapping."""
    assert "no `x<count>` suffix" in spec_text() or "admits **no `x<count>` suffix**" in spec_text(), (
        "DRIFT [grammar.new-game]: SPEC.md §2.1 no longer states the "
        "exact-literal/no-suffix rule"
    )
    new_game = mapping_tokens()["new-game"]
    assert new_game["repeatable"] is False, (
        "DRIFT [tokens.new-game.repeatable]: mapping/v1.json marks new-game "
        "repeatable — SPEC.md §2.1 forbids any suffix"
    )
    suffixed = [t for t in mapping()["canonical_titles"] if t.startswith(new_game["title"] + " x")]
    assert not suffixed, (
        f"DRIFT [canonical_titles]: suffixed new-game literals {suffixed} — "
        "SPEC.md §2.1 admits the exact literal only"
    )


# --- Control links and placeholder (SPEC §9) -----------------------------------

@functools.lru_cache(maxsize=1)
def spec_control_links():
    listing = extract(
        r"Rendered links \((\d+), in this order\): (.+?)\. Labels",
        field="control_links", flags=re.S, group=2,
    )
    count = int(extract(r"Rendered links \((\d+), in this order\)", field="control_links.count"))
    links = ["doom: " + part.strip().strip("`") for part in listing.split(",")]
    return count, links


def test_control_links_match_spec_order_exactly():
    _, spec_links = spec_control_links()
    json_links = mapping()["control_links"]
    assert json_links == spec_links, (
        f"DRIFT [control_links]: mapping/v1.json={json_links} — "
        f"game/SPEC.md §9={spec_links} (order-sensitive)"
    )


def test_control_link_count_matches_spec_and_the_declared_grid():
    count, spec_links = spec_control_links()
    json_links = mapping()["control_links"]
    assert len(json_links) == count == len(spec_links), (
        f"DRIFT [control_links.count]: mapping/v1.json has {len(json_links)} — "
        f"game/SPEC.md §9 states {count}"
    )
    columns = int(extract(r"Layout: \*\*(\d+) columns\*\*", field="control_links.columns"))
    rows = int(extract(r"Layout: \*\*\d+ columns\*\*, (\d+) rows", field="control_links.rows"))
    assert columns * rows == count, (
        f"DRIFT [control_links.grid]: SPEC.md §9 declares a {columns}x{rows} "
        f"layout but lists {count} links"
    )


def test_every_control_link_is_a_canonical_title():
    json_links = mapping()["control_links"]
    orphans = [t for t in json_links if t not in mapping()["canonical_titles"]]
    assert not orphans, (
        f"DRIFT [control_links]: {orphans} are not in canonical_titles — "
        "the README would render an unplayable control"
    )


def test_disabled_controls_placeholder_is_byte_identical_to_spec():
    spec_placeholder = extract(
        r"instead of the table: `([^`]+)`", field="controls_disabled_placeholder"
    )
    json_placeholder = mapping()["controls_disabled_placeholder"]
    assert json_placeholder == spec_placeholder, (
        f"DRIFT [controls_disabled_placeholder]: mapping/v1.json="
        f"{json_placeholder!r} — game/SPEC.md §9={spec_placeholder!r}"
    )


# --- Knobs (SPEC §6) ------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def spec_knob_rows():
    """Parse the section 6 knob table into {row-label: value-cell}."""
    rows = {}
    for line in spec_text().splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line[1:-1].split("|")]
        if len(cells) != 3 or cells[0] in ("Knob", "---"):
            continue
        rows[cells[0]] = cells[1]
    return rows


def spec_knob_cell(knob_key):
    pattern = KNOB_ROW_PATTERNS[knob_key]
    matches = [value for label, value in spec_knob_rows().items() if re.search(pattern, label)]
    assert len(matches) == 1, (
        f"DRIFT [knobs.{knob_key}]: expected exactly one game/SPEC.md §6 row "
        f"matching {pattern!r}, found {len(matches)}"
    )
    bold = re.search(r"\*\*(.+?)\*\*", matches[0])
    assert bold, (
        f"DRIFT [knobs.{knob_key}]: the SPEC.md §6 value cell {matches[0]!r} "
        "no longer carries a bolded value"
    )
    return bold.group(1)


@pytest.mark.parametrize("knob_key", sorted(KNOB_ROW_PATTERNS))
def test_knob_value_matches_spec(knob_key):
    cell = spec_knob_cell(knob_key)
    backticked = re.search(r"`([^`]+)`", cell)
    spec_value = backticked.group(1) if backticked else to_int(cell)
    json_value = mapping()["knobs"].get(knob_key)
    assert json_value == spec_value, (
        f"DRIFT [knobs.{knob_key}]: mapping/v1.json has {json_value!r} — "
        f"game/SPEC.md §6 states {spec_value!r}"
    )


def test_knob_key_sets_are_symmetric():
    json_keys = set(mapping()["knobs"])
    linked_keys = set(KNOB_ROW_PATTERNS)
    assert json_keys == linked_keys, (
        f"DRIFT [knobs]: mapping/v1.json has unlinked keys "
        f"{sorted(json_keys - linked_keys)}; SPEC-linked keys with no mapping "
        f"entry: {sorted(linked_keys - json_keys)}"
    )


def test_title_byte_cap_agrees_between_spec_sections_4_and_6():
    section_4 = int(extract(r"\*\*Title byte cap: (\d+) bytes", field="knobs.title_byte_cap"))
    section_6 = to_int(spec_knob_cell("title_byte_cap"))
    assert section_4 == section_6, (
        f"DRIFT [knobs.title_byte_cap]: game/SPEC.md §4 states {section_4} "
        f"but §6 states {section_6} — SPEC is self-inconsistent"
    )


# --- Latency (SPEC §7) ----------------------------------------------------------

@pytest.mark.parametrize("latency_key", sorted(LATENCY_PATTERNS))
def test_latency_value_matches_spec(latency_key):
    pattern = LATENCY_PATTERNS[latency_key]
    match = re.search(pattern, spec_text())
    assert match is not None, (
        f"DRIFT [latency.{latency_key}]: game/SPEC.md §7 no longer states this "
        f"value in the expected form (pattern {pattern!r})"
    )
    number, unit = match.group(1), match.group(2)
    spec_value = int(number) if not unit else to_seconds(number, unit)
    json_value = mapping()["latency"].get(latency_key)
    assert json_value == spec_value, (
        f"DRIFT [latency.{latency_key}]: mapping/v1.json has {json_value!r} — "
        f"game/SPEC.md §7 states {number} {unit or 'moves'} ({spec_value})"
    )


def test_latency_key_sets_are_symmetric():
    json_keys = set(mapping()["latency"])
    linked_keys = set(LATENCY_PATTERNS)
    assert json_keys == linked_keys, (
        f"DRIFT [latency]: mapping/v1.json has unlinked keys "
        f"{sorted(json_keys - linked_keys)}; missing entries: "
        f"{sorted(linked_keys - json_keys)}"
    )


def test_latency_thresholds_are_internally_ordered():
    latency = mapping()["latency"]
    assert latency["stretch_p50_seconds"] < latency["target_seconds"] < latency["defect_p50_seconds"], (
        f"DRIFT [latency]: stretch < target < defect violated by {latency}"
    )


# --- Budget (SPEC §12) -----------------------------------------------------------

@functools.lru_cache(maxsize=1)
def spec_ladder():
    rungs = re.findall(
        r"\*\*(L\d)\*\*: (\d+) s tail @ (\d+) px[^/]*/ (\d+) fps / (\d+) colors",
        spec_text(),
    )
    assert rungs, "DRIFT [budget.ladder]: could not parse the SPEC.md §12 re-encode ladder"
    return [
        {"level": level, "tail_seconds": int(tail), "width_px": int(width),
         "fps": int(fps), "colors": int(colors)}
        for level, tail, width, fps, colors in rungs
    ]


def test_budget_ceiling_matches_spec():
    spec_value = to_int(
        extract(r"Hard byte ceiling: [\d.]+ MB = ([\d,]+) bytes", field="budget.ceiling_bytes")
    )
    json_value = mapping()["budget"]["ceiling_bytes"]
    assert json_value == spec_value, (
        f"DRIFT [budget.ceiling_bytes]: mapping/v1.json has {json_value} — "
        f"game/SPEC.md §12 states {spec_value}"
    )


def test_budget_floor_matches_spec():
    spec_value = to_int(
        extract(r"Hard byte floor: ([\d,]+) bytes", field="budget.floor_bytes")
    )
    json_value = mapping()["budget"]["floor_bytes"]
    assert json_value == spec_value, (
        f"DRIFT [budget.floor_bytes]: mapping/v1.json has {json_value} — "
        f"game/SPEC.md §12 states {spec_value}"
    )


def test_budget_floor_is_below_the_ceiling():
    budget = mapping()["budget"]
    assert budget["floor_bytes"] < budget["ceiling_bytes"], (
        f"DRIFT [budget]: floor_bytes {budget['floor_bytes']} is not below "
        f"ceiling_bytes {budget['ceiling_bytes']} — the publish band is empty"
    )
    assert budget["floor_bytes"] > 0, (
        "DRIFT [budget.floor_bytes]: a non-positive floor gates nothing"
    )


def test_structure_constants_match_spec():
    """SPEC 12.1 step 1 evidence, authored once and mirrored in the mapping."""
    structure = mapping()["budget"]["structure"]
    spec_magic = extract(r"`(GIF89a)` magic", field="budget.structure.magic_hex")
    assert bytes.fromhex(structure["magic_hex"]) == spec_magic.encode("ascii"), (
        f"DRIFT [budget.structure.magic_hex]: mapping/v1.json decodes to "
        f"{bytes.fromhex(structure['magic_hex'])!r} — game/SPEC.md §12.1 "
        f"states {spec_magic!r}"
    )
    spec_trailer = extract(r"trailer byte `0x([0-9A-Fa-f]{2})`",
                           field="budget.structure.trailer_hex")
    assert structure["trailer_hex"].lower() == spec_trailer.lower(), (
        f"DRIFT [budget.structure.trailer_hex]: mapping/v1.json has "
        f"{structure['trailer_hex']!r} — game/SPEC.md §12.1 states {spec_trailer!r}"
    )


def test_structure_evidence_reads_both_ends():
    """The residual §0.3 requires stated: head-only evidence cannot detect
    truncation, so both constants must be present and distinct."""
    structure = mapping()["budget"]["structure"]
    assert set(structure) == {"magic_hex", "trailer_hex"}, (
        f"DRIFT [budget.structure]: expected exactly magic_hex and trailer_hex, "
        f"got {sorted(structure)}"
    )
    for key in ("magic_hex", "trailer_hex"):
        assert structure[key], f"DRIFT [budget.structure.{key}]: empty gates nothing"
        bytes.fromhex(structure[key])  # must decode


def test_reason_codes_match_the_spec_enum():
    """SPEC 5.7 is a closed enum of six; the workflow branches on these codes,
    so mapping and SPEC must agree exactly."""
    spec_codes = re.findall(r"^\| `([a-z-]+)` \| `close-\w+` \|", spec_text(), re.M)
    assert spec_codes, "DRIFT [reason_codes]: could not parse the SPEC §5.7 table"
    json_codes = mapping()["reason_codes"]
    assert json_codes == spec_codes, (
        f"DRIFT [reason_codes]: mapping/v1.json={json_codes} — "
        f"game/SPEC.md §5.7={spec_codes} (order-sensitive)"
    )


def test_section_states_match_the_spec_enum():
    """SPEC 5.8 is a closed set of three in PRECEDENCE order sealed > capped >
    open. The consumer selects a state screen by looking the value up, so a
    reordering or a rename is a runtime contract change, not cosmetics."""
    contract = re.search(
        r'"section":\s*\{\s*"state":\s*(.+?)\s*\}', spec_text()
    )
    assert contract, "DRIFT [section_states]: could not parse the SPEC §5.8 contract"
    spec_states = re.findall(r'"([a-z-]+)"', contract.group(1))
    assert spec_states, "DRIFT [section_states]: SPEC §5.8 contract lists no states"
    json_states = mapping()["section_states"]
    assert json_states == spec_states, (
        f"DRIFT [section_states]: mapping/v1.json={json_states} — "
        f"game/SPEC.md §5.8={spec_states} (order-sensitive: it is the "
        f"precedence order)"
    )


def test_section_state_enum_is_closed_at_three():
    stated = extract(r"\*\*Closed set of (\w+), in precedence order\*\*",
                     field="section_states.count")
    json_states = mapping()["section_states"]
    assert stated.lower() in ("three", "3"), (
        f"DRIFT [section_states]: game/SPEC.md §5.8 declares a closed set of "
        f"{stated!r}"
    )
    assert len(json_states) == 3, (
        f"DRIFT [section_states]: mapping/v1.json lists {len(json_states)}"
    )
    assert len(set(json_states)) == len(json_states), "duplicate section state"


def test_section_state_precedence_is_stated_in_the_spec():
    """The precedence is the whole reason the order is normative: a section can
    satisfy both `sealed` and `capped`, and `sealed` must win."""
    states = mapping()["section_states"]
    prose = spec_text()
    sealed_at = prose.find("`sealed` (any header pin")
    capped_at = prose.find("`capped` (the section is at or above")
    assert sealed_at != -1 and capped_at != -1, (
        "DRIFT [section_states]: SPEC §5.8 no longer states the precedence"
    )
    assert sealed_at < capped_at, (
        "DRIFT [section_states]: SPEC §5.8 states capped before sealed"
    )
    assert states.index("sealed") < states.index("capped") < states.index("open"), (
        f"DRIFT [section_states]: mapping order {states} is not the precedence order"
    )


def test_adding_section_states_did_not_widen_the_reason_code_enum():
    """SPEC 5.7 is explicitly unchanged by SPEC 5.8: section state is a separate
    top-level field, not a seventh code. The two share the literal `sealed` by
    design — they answer different questions at different cardinalities — so
    this guards the COUNT, not disjointness."""
    assert "section-cap" in mapping()["reason_codes"], (
        "DRIFT [reason_codes]: the cap reason code was renamed or removed"
    )
    assert "capped" not in mapping()["reason_codes"], (
        "DRIFT [reason_codes]: a SPEC §5.8 section state leaked into the §5.7 enum"
    )
    assert "open" not in mapping()["reason_codes"], (
        "DRIFT [reason_codes]: a SPEC §5.8 section state leaked into the §5.7 enum"
    )


def test_reason_code_enum_is_closed_at_six():
    stated = int(extract(r"\*\*Closed set of (\w+)\.\*\*", field="reason_codes.count")
                 .replace("six", "6"))
    json_codes = mapping()["reason_codes"]
    assert len(json_codes) == stated == 6, (
        f"DRIFT [reason_codes]: mapping/v1.json lists {len(json_codes)} — "
        f"game/SPEC.md §5.7 declares a closed set of {stated}"
    )
    assert len(set(json_codes)) == len(json_codes), "duplicate reason code"


def test_ladder_rung_count_matches_spec():
    spec_rungs = spec_ladder()
    json_rungs = mapping()["budget"]["ladder"]
    assert len(json_rungs) == len(spec_rungs), (
        f"DRIFT [budget.ladder]: mapping/v1.json has {len(json_rungs)} rungs "
        f"({[r.get('level') for r in json_rungs]}) — game/SPEC.md §12 has "
        f"{len(spec_rungs)} ({[r['level'] for r in spec_rungs]})"
    )


@pytest.mark.parametrize("index", range(len(spec_ladder())))
@pytest.mark.parametrize("field", LADDER_FIELDS)
def test_ladder_rung_field_matches_spec(index, field):
    spec_rung = spec_ladder()[index]
    json_ladder = mapping()["budget"]["ladder"]
    assert index < len(json_ladder), (
        f"DRIFT [budget.ladder[{index}]]: absent from mapping/v1.json — "
        f"game/SPEC.md §12 defines {spec_rung['level']}"
    )
    json_rung = json_ladder[index]
    assert json_rung.get(field) == spec_rung[field], (
        f"DRIFT [budget.ladder[{index}].{field}] ({spec_rung['level']}): "
        f"mapping/v1.json has {json_rung.get(field)!r} — "
        f"game/SPEC.md §12 has {spec_rung[field]!r}"
    )


def test_ladder_tail_seconds_are_monotonically_non_increasing():
    tails = [rung["tail_seconds"] for rung in mapping()["budget"]["ladder"]]
    assert tails == sorted(tails, reverse=True), (
        f"DRIFT [budget.ladder.tail_seconds]: {tails} increases down the ladder — "
        "each rung must shrink the clip, never grow it"
    )
    assert all(t > 0 for t in tails), f"DRIFT [budget.ladder.tail_seconds]: non-positive tail in {tails}"


def test_ladder_quality_never_increases_down_the_rungs():
    ladder = mapping()["budget"]["ladder"]
    for field in ("width_px", "fps", "colors"):
        values = [rung[field] for rung in ladder]
        assert values == sorted(values, reverse=True), (
            f"DRIFT [budget.ladder.{field}]: {values} increases down the ladder — "
            "each rung must reduce cost, never raise it"
        )


# --- Top-level scalars ------------------------------------------------------------

def test_mapping_version_matches_spec():
    spec_value = int(extract(r"Mapping version: \*\*(\d+)\*\*", field="mapping_version"))
    json_value = mapping()["mapping_version"]
    assert json_value == spec_value, (
        f"DRIFT [mapping_version]: mapping/v1.json has {json_value} — "
        f"game/SPEC.md states {spec_value}"
    )


def test_engine_fps_matches_spec():
    spec_value = int(extract(r"\*\*(\d+) tics/sec\*\*", field="engine_fps"))
    json_value = mapping()["engine_fps"]
    assert json_value == spec_value, (
        f"DRIFT [engine_fps]: mapping/v1.json has {json_value} — "
        f"game/SPEC.md states {spec_value} tics/sec"
    )


def test_spec_carries_no_unresolved_placeholders():
    leftovers = re.findall(r"\b(TBD|TODO|FIXME|\?\?\?)\b", spec_text(), re.I)
    assert not leftovers, (
        f"DRIFT [SPEC.md]: unresolved placeholder(s) {sorted(set(leftovers))} — "
        "every normative value must be resolved at plan time"
    )
