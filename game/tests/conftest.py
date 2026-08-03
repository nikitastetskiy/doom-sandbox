"""Shared harness for the E3 red-phase suite (plan 01-playable-doom-readme).

Tests exercise the RFC-mandated standalone scripts in ``game/scripts/`` as
subprocesses (files/env in, files + exit code out) and the ``gamelog``
serialization module via lazy import. While an implementation file is absent
(red phase) every test fails through ``run_script`` / ``import_gamelog`` with
an explicit "missing implementation" message -- never a collection error.

Normative values are pinned VERBATIM from ``game/SPEC.md`` and
``game/mapping/v1.json`` (mapping_version 1). If these constants ever disagree
with those artifacts, the spec artifacts win and the disagreement is a build
error (SPEC preamble rule).
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# --- Repo geometry ---------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
GAME_DIR = REPO_ROOT / "game"
SCRIPTS_DIR = GAME_DIR / "scripts"
MAPPING_PATH = GAME_DIR / "mapping" / "v1.json"
TOOLCHAIN_PATH = GAME_DIR / "toolchain.json"
README_PATH = REPO_ROOT / "README.md"
FIXTURES_DIR = GAME_DIR / "tests" / "fixtures"  # E2-owned; read-only for E3
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "doom.yml"

# --- SPEC values, pinned VERBATIM (game/SPEC.md sections 1-12) -------------
MAPPING_VERSION = 1

# SPEC section 1: token enum -- id -> (canonical title, keys/frame, frames, repeatable)
TOKENS = {
    "forward":     {"title": "doom: forward",     "keys": "u",  "frames": 18, "repeatable": True},
    "back":        {"title": "doom: back",        "keys": "d",  "frames": 18, "repeatable": True},
    "turn-left":   {"title": "doom: turn-left",   "keys": "l",  "frames": 10, "repeatable": True},
    "turn-right":  {"title": "doom: turn-right",  "keys": "r",  "frames": 10, "repeatable": True},
    "fire":        {"title": "doom: fire",        "keys": "f",  "frames": 8,  "repeatable": True},
    "use":         {"title": "doom: use",         "keys": "p",  "frames": 4,  "repeatable": False},
    "run-forward": {"title": "doom: run-forward", "keys": "su", "frames": 18, "repeatable": True},
    "new-game":    {"title": "doom: new game",    "keys": "",   "frames": 0,  "repeatable": False},
}
REPEAT_MIN, REPEAT_MAX = 2, 9            # SPEC section 2
TITLE_BYTE_CAP = 64                      # SPEC section 4
CANONICAL_TITLE_COUNT = 56               # SPEC section 3: 8 + 6 * 8

# SPEC section 5 grammars
STREAM_GRAMMAR_ALPHABET = set("udlrfps<>0123456789")  # 5.4 -- e/x absent by design
V1_EXPANSION_ALPHABET = set("udlrfps")                # 5.4 -- v1 expansions subset
TOKEN_IDS = tuple(TOKENS)

# SPEC section 6 knob values
NEW_GAME_COOLDOWN_MINUTES = 30
DRAIN_CAP_ISSUES_PER_RUN = 20
SECTION_CAP_FRAMES = 120_000
PUSH_RETRY_ATTEMPTS = 3
LOG_FULL_MESSAGE = "log full — start a new game"  # SPEC section 6, verbatim
# SPEC 5.5 rule 3, verbatim — no interpolation, parallel to LOG_FULL_MESSAGE
SEALED_MESSAGE = "the arcade is being upgraded — press New game to continue"

# SPEC section 9: control table
ISSUE_URL_PREFIX = "https://github.com/nikitastetskiy/nikitastetskiy/issues/new?title="
ISSUE_BODY_PARAM = "Just%20press%20Submit%20%E2%80%94%20your%20move%20runs%20automatically."
CONTROL_LINKS = [
    "doom: forward",
    "doom: forward x5",
    "doom: run-forward x5",
    "doom: back",
    "doom: turn-left",
    "doom: turn-right",
    "doom: turn-left x3",
    "doom: turn-right x3",
    "doom: fire",
    "doom: fire x3",
    "doom: use",
    "doom: new game",
]
CONTROL_TABLE_COLUMNS = 3
CONTROL_TABLE_ROWS = 4

# SPEC section 12 / RFC D7: budget constants (normative, untouchable)
BUDGET_CEILING_BYTES = 4_000_000
BUDGET_FLOOR_BYTES = 16_000  # SPEC 12: mapping budget.floor_bytes
# SPEC 12.1 measured reference points that fix the discriminating band.
STILL_FRAME_BYTES = 46_000       # legitimate single-frame still — MUST publish
CLIP_18_FRAME_BYTES = 276_000    # legitimate 18-frame clip — MUST publish
COLLAPSE_SIGNATURE_BYTES = 3_000  # recorded palette-collapse signature — MUST fail
LADDER_LEVELS = ("L0", "L1", "L2")
# px/fps/colors per rung -- identical in both the E1 and the E2-adjusted SPEC;
# tail_seconds is plan-tunable and therefore consumed from mapping/v1.json.
LADDER_PX_FPS_COLORS = {"L0": (320, 12, 128), "L1": (320, 12, 128), "L2": (256, 10, 64)}

# RFC must_have 8: marker literals
MARKER_START = "<!-- DOOM:START -->"
MARKER_END = "<!-- DOOM:END -->"
MARKER_START_B = MARKER_START.encode("ascii")
MARKER_END_B = MARKER_END.encode("ascii")

# Deterministic dummy pins for section headers (grammar-valid lowercase hex)
ENGINE_HEX = "ab" * 20   # 40 hex chars
BUILD_HEX = "cd" * 32    # 64 hex chars
WAD_HEX = "ef" * 32      # 64 hex chars

MISSING_IMPL_FMT = (
    "missing implementation: {path} — expected E3 red phase; "
    "implement per the @spec-handoff block of this test file (plan step E4)"
)


# --- Script invocation harness --------------------------------------------
def script_path(name: str) -> Path:
    return SCRIPTS_DIR / name


def run_script(name, args=(), *, env=None, cwd=None, stdin=b"", timeout=60):
    """Run game/scripts/<name> as a subprocess; red-fail if it does not exist."""
    path = script_path(name)
    if not path.is_file():
        pytest.fail(MISSING_IMPL_FMT.format(path=f"game/scripts/{name}"), pytrace=False)
    full_env = dict(os.environ)
    full_env.pop("DOOM_TITLE", None)  # never inherit a title from the outer env
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(path), *[str(a) for a in args]],
        capture_output=True,
        env=full_env,
        cwd=str(cwd or REPO_ROOT),
        input=stdin,
        timeout=timeout,
    )


def import_gamelog():
    """Lazily import game/scripts/gamelog.py; red-fail if absent."""
    path = script_path("gamelog.py")
    if not path.is_file():
        pytest.fail(MISSING_IMPL_FMT.format(path="game/scripts/gamelog.py"), pytrace=False)
    spec = importlib.util.spec_from_file_location("gamelog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_stdout(proc):
    """Decode a script's single-line JSON stdout, failing with context."""
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except Exception:
        pytest.fail(
            "script stdout is not a single JSON document: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )


# --- Parser helpers --------------------------------------------------------
def run_parser(title=None, *, transport="json", tmp_path=None, extra_args=()):
    """Invoke parse_title.py with the title via env or JSON file (never argv)."""
    args = list(extra_args)
    env = {}
    if transport == "env":
        env["DOOM_TITLE"] = title
    elif transport == "json":
        assert tmp_path is not None, "json transport needs tmp_path"
        payload = tmp_path / "title.json"
        payload.write_text(json.dumps({"title": title}), encoding="utf-8")
        args += ["--json", str(payload)]
    elif transport == "none":
        pass
    else:  # pragma: no cover - harness guard
        raise AssertionError(f"unknown transport {transport}")
    return run_script("parse_title.py", args, env=env)


def canonical_expected():
    """The full 56-literal canonical set with expected (token, count) results.

    Generation rule from SPEC section 3: each base literal once (count 1), plus
    ``<literal> x<n>`` for every repeatable token and n = 2..9.
    """
    expected = {}
    for token_id, spec in TOKENS.items():
        expected[spec["title"]] = (token_id, 1)
        if spec["repeatable"]:
            for n in range(REPEAT_MIN, REPEAT_MAX + 1):
                expected[f"{spec['title']} x{n}"] = (token_id, n)
    return expected


# --- Serialization helpers -------------------------------------------------
def section_header(n=1, mapping=MAPPING_VERSION, engine=ENGINE_HEX, build=BUILD_HEX, wad=WAD_HEX):
    return f"#section {n} engine={engine} build={build} wad={wad} mapping={mapping}"


def ledger_line(ts, handle, token, count, issue):
    return f"{ts} {handle} {token} {count} #{issue}"


def make_toolchain(tmp_path, *, engine=ENGINE_HEX, wad=WAD_HEX, build=BUILD_HEX,
                   name="toolchain.json"):
    """Minimal game/toolchain.json shape carrying the pins SPEC 5.5 compares.

    Defaults match the section_header() defaults, so a ledger built with
    make_section_text() is NOT sealed against this toolchain. Override any pin
    to seal the current section.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_text(json.dumps({
        "toolchain_version": 1,
        "runner_image": "ubuntu-24.04",
        "engine": {"commit_sha": engine,
                   "build_sha256": {"value": build, "status": "provisional_local"}},
        "wad": {"file": "game/assets/freedoom1.wad", "sha256": wad},
    }), encoding="utf-8")
    return path


def sealed_section_text(lines=(), n=1, engine="99" * 20, mapping=MAPPING_VERSION):
    """A section whose header pins disagree with make_toolchain()'s defaults."""
    header = section_header(n=n, engine=engine, mapping=mapping)
    return "\n".join([header, *lines]) + "\n"


def make_section_text(lines, n=1, mapping=MAPPING_VERSION):
    """One SPEC 5.1 section: header + ledger lines, LF-joined, one trailing LF."""
    return "\n".join([section_header(n=n, mapping=mapping), *lines]) + "\n"


def expected_stream_text(moves):
    """Canonical stream for [(token_id, count), ...] per SPEC 5.4."""
    frames = []
    for token_id, count in moves:
        spec = TOKENS[token_id]
        frames.extend([spec["keys"]] * (spec["frames"] * count))
    return ",".join(frames) + "\n"


# --- README helpers --------------------------------------------------------
def make_readme_bytes(block=b"initial game block\n", prefix=None, suffix=None):
    """A profile README with identity content outside the DOOM marker block."""
    if prefix is None:
        prefix = (
            "# Nik Stetskiy\n\nProfile prose with unicode — 日本語 🚀 — that the "
            "rewriter must never touch.\n\n"
        ).encode("utf-8")
    if suffix is None:
        suffix = "\n## Links\n\n- [site](https://example.com)\nTrailing prose.\n".encode("utf-8")
    return prefix + MARKER_START_B + b"\n" + block + MARKER_END_B + b"\n" + suffix


def block_bounds_bytes(data: bytes):
    """(start, end) byte offsets of the region strictly between the marker lines."""
    s = data.index(MARKER_START_B)
    s_end = data.index(b"\n", s) + 1
    e = data.index(MARKER_END_B)
    e_start = data.rfind(b"\n", 0, e) + 1
    return s_end, e_start


def outside_parts_bytes(data: bytes):
    """(before, after) — everything the rewriter must leave byte-identical.

    NOTE: both parts INCLUDE their marker line (`before` ends with
    "<!-- DOOM:START -->\\n"; `after` begins with "<!-- DOOM:END -->\\n"), by
    design — the marker lines are themselves outside-the-block bytes and must
    survive every rewrite. Compare helper output against helper output
    (`outside_parts_bytes(rewritten) == outside_parts_bytes(original)`), never
    against a raw prefix/suffix you passed to make_readme_bytes(): those do not
    include the marker lines and the comparison will fail spuriously.
    """
    start, end = block_bounds_bytes(data)
    return data[:start], data[end:]


def inside_block_bytes(data: bytes) -> bytes:
    start, end = block_bounds_bytes(data)
    return data[start:end]


def run_rewriter(readme_path, *, state, image_url, controls_enabled=False,
                 mapping=MAPPING_PATH, extra_args=()):
    args = ["--readme", str(readme_path), "--mapping", str(mapping),
            "--state", state, "--image-url", image_url]
    if controls_enabled:
        args.append("--controls-enabled")
    args += list(extra_args)
    return run_script("rewrite_readme.py", args)


# --- Budget helpers --------------------------------------------------------
def run_budget(rung, *, size=None, file=None, mapping=MAPPING_PATH):
    args = ["--mapping", str(mapping), "--rung", rung]
    if size is not None:
        args += ["--size", str(size)]
    if file is not None:
        args += ["--file", str(file)]
    return run_script("budget.py", args)


# SPEC 12.1 gate step 1, mirrored in mapping budget.structure.
GIF89A_MAGIC = b"GIF89a"   # magic_hex 474946383961 — proves a writer STARTED
GIF_TRAILER = b"\x3b"      # trailer_hex 3b — proves a writer FINISHED


def sparse_file(tmp_path, name, size, *, magic=GIF89A_MAGIC, trailer=GIF_TRAILER):
    """Create a file of exactly `size` bytes without writing `size` bytes.

    Fixtures are structurally complete by default — GIF89a head AND 0x3B tail —
    because SPEC 12.1 step 1 establishes "the complete output of a GIF writer"
    from BOTH ends. A fixture that merely started with the magic would now be a
    truncated artifact and fail the gate.

    Escapes for building deliberately broken artifacts:
      magic=b""    -> not a GIF at all (wrong file: PNG, HTML error page)
      trailer=b""  -> valid header, unterminated body (TRUNCATED)
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    head = magic[:size]
    with open(path, "wb") as fh:
        fh.write(head)
        if size > len(head):
            fh.seek(size - 1)
            fh.write(trailer[:1] if trailer else b"\0")
    assert path.stat().st_size == size
    return path


def assert_fixture_shape(path, *, magic, trailer, size=None):
    """Assert a fixture IS the artifact the test intends, before asserting what
    the gate does to it.

    A test whose name describes truncation while its fixture strips the magic
    asserts a different predicate than it advertises — the prose-vs-predicate
    gap SPEC section 0 exists to prevent, reproduced in test names. Call this
    first so the fixture cannot silently drift from the case being claimed.
    """
    blob = path.read_bytes()
    if size is not None:
        assert len(blob) == size, f"fixture size {len(blob)}, expected {size}"
    has_magic = blob[:len(GIF89A_MAGIC)] == GIF89A_MAGIC
    has_trailer = blob[-1:] == GIF_TRAILER
    assert has_magic is magic, (
        f"fixture magic: got {blob[:6]!r}, expected GIF89a present={magic}"
    )
    assert has_trailer is trailer, (
        f"fixture trailer: got {blob[-1:]!r}, expected 0x3B present={trailer}"
    )
    return path


# --- Drain helpers ---------------------------------------------------------
def make_issue(number, title, created_at, login="visitor"):
    """GitHub REST subset consumed by drain.py (issues are JSON files, never API)."""
    return {"number": number, "title": title, "created_at": created_at,
            "user": {"login": login}}


def run_drain(tmp_path, issues, ledger_text, *, mapping=MAPPING_PATH, toolchain=None,
              extra_args=()):
    """Run drain.py. `toolchain` defaults to pins that MATCH section_header(),
    so callers that do not care about SPEC 5.5 sealing get an unsealed run."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(issues), encoding="utf-8")
    ledger_path = tmp_path / "log.txt"
    ledger_path.write_text(ledger_text, encoding="ascii")
    moves_path = tmp_path / "moves.out"
    actions_path = tmp_path / "actions.json"
    if toolchain is None:
        toolchain = make_toolchain(tmp_path)
    proc = run_script(
        "drain.py",
        ["--issues", str(issues_path), "--ledger", str(ledger_path),
         "--mapping", str(mapping), "--toolchain", str(toolchain),
         "--out-moves", str(moves_path),
         "--out-actions", str(actions_path), *extra_args],
    )
    return proc, moves_path, actions_path


def load_actions(actions_path):
    return json.loads(actions_path.read_text(encoding="utf-8"))


# --- Mapping helpers -------------------------------------------------------
def load_mapping():
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def write_mapping(tmp_path, mapping_dict, name="mapping.json"):
    path = tmp_path / name
    path.write_text(json.dumps(mapping_dict), encoding="utf-8")
    return path


# --- Workflow harness ------------------------------------------------------
# The shell that decides what a run does lives in .github/workflows/doom.yml,
# so a test that hand-transcribes it into Python asserts against a COPY and
# proves nothing about the file that ships. Every workflow test here extracts
# the step's `run:` body VERBATIM from the YAML and executes that text. If the
# workflow is edited, the test executes the edit; there is no second copy to
# drift. game/tests owns none of doom.yml — these helpers read it, never write.


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _literal_block_at(lines, key_line_index):
    """Body of the literal block scalar opened on `lines[key_line_index]`.

    Returns the dedented text with a single trailing LF — byte-identical to
    what a YAML parser yields for `|` / `|-` under this workflow's shapes
    (asserted against PyYAML by the extraction test, where PyYAML is present).
    """
    header = lines[key_line_index].split(":", 1)[1].strip()
    if header not in ("|", "|-"):
        return None
    body, body_indent = [], None
    for line in lines[key_line_index + 1:]:
        if not line.strip():
            body.append("")
            continue
        indent = _indent_of(line)
        if body_indent is None:
            body_indent = indent
        if indent < body_indent:
            break
        body.append(line[body_indent:])
    while body and not body[-1]:
        body.pop()
    return "\n".join(body) + "\n"


def workflow_lines(workflow=WORKFLOW_PATH):
    return workflow.read_text(encoding="utf-8").splitlines()


def workflow_step_run(step_name, workflow=WORKFLOW_PATH):
    """The `run:` script of the uniquely-named workflow step, verbatim.

    Fails loudly rather than returning something plausible: a silently wrong
    extraction would run a DIFFERENT script than the one under test and could
    still go green.
    """
    lines = workflow_lines(workflow)
    start = step_indent = None
    for index, line in enumerate(lines):
        if line.strip() == f"- name: {step_name}":
            assert start is None, f"step name {step_name!r} is not unique in {workflow.name}"
            start, step_indent = index, _indent_of(line)
    assert start is not None, f"no step named {step_name!r} in {workflow.name}"
    key_indent = step_indent + 2
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and _indent_of(line) <= step_indent:
            break
        if _indent_of(line) == key_indent and line.strip().startswith("run:"):
            script = _literal_block_at(lines, index)
            assert script is not None, (
                f"step {step_name!r} does not use a literal block scalar for `run:`"
            )
            return script
    raise AssertionError(f"step {step_name!r} has no `run:` script")


def workflow_run_blocks(workflow=WORKFLOW_PATH):
    """[(step name, run script)] for every literal-block `run:` in the file."""
    lines = workflow_lines(workflow)
    blocks, current = [], "<unnamed>"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- name: "):
            current = stripped[len("- name: "):]
        elif stripped.startswith("run:"):
            script = _literal_block_at(lines, index)
            if script is not None:
                blocks.append((current, script))
    return blocks


def workflow_step_field(step_name, field, workflow=WORKFLOW_PATH):
    """Raw text of a scalar step key (`if:`, `id:`), folded onto one line.

    Only for structural assertions ABOUT the workflow's wiring. Never used to
    re-evaluate an Actions expression in Python: re-implementing the expression
    language is the retype-the-normative-thing mistake this suite exists to
    catch.
    """
    lines = workflow_lines(workflow)
    start = step_indent = None
    for index, line in enumerate(lines):
        if line.strip() == f"- name: {step_name}":
            start, step_indent = index, _indent_of(line)
    assert start is not None, f"no step named {step_name!r} in {workflow.name}"
    key_indent = step_indent + 2
    collected = None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and _indent_of(line) <= step_indent:
            break
        indent = _indent_of(line)
        if indent == key_indent and line.strip().startswith(f"{field}:"):
            collected = [line.strip()[len(field) + 1:].strip()]
            continue
        if collected is not None:
            if line.strip().startswith("#"):
                continue
            if not line.strip() or indent <= key_indent:
                break
            collected.append(line.strip())
    assert collected is not None, f"step {step_name!r} has no `{field}:`"
    return " ".join(part for part in collected if part not in ("", ">-", ">", "|"))


def parse_github_output(path: Path):
    """`$GITHUB_OUTPUT` as a dict. Values may contain `=`; keys may not."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    outputs = {}
    for line in text.splitlines():
        if not line:
            continue
        key, sep, value = line.partition("=")
        assert sep, f"malformed GITHUB_OUTPUT line: {line!r}"
        outputs[key] = value
    return outputs


class StepResult:
    """Everything a workflow step communicates: exit code, logs, outputs, summary."""

    def __init__(self, proc, outputs, summary):
        self.proc, self.outputs, self.summary = proc, outputs, summary
        self.returncode = proc.returncode
        self.stdout = proc.stdout.decode("utf-8", "replace")
        self.stderr = proc.stderr.decode("utf-8", "replace")

    @property
    def log(self):
        """Workflow log commands (`::error::`, `::notice::`) land on stdout."""
        return self.stdout + self.stderr

    def __repr__(self):  # pragma: no cover - only rendered on failure
        return (f"StepResult(rc={self.returncode}, outputs={self.outputs!r}, "
                f"log={self.log!r}, summary={self.summary!r})")


def run_workflow_step(script, *, runner_temp, env=None, cwd=None, timeout=120):
    """Execute an extracted step body the way a runner does: bash, env, files."""
    runner_temp.mkdir(parents=True, exist_ok=True)
    output_path = runner_temp / "github_output"
    summary_path = runner_temp / "github_step_summary"
    output_path.write_text("", encoding="utf-8")
    summary_path.write_text("", encoding="utf-8")
    full_env = dict(os.environ)
    full_env.update({
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "MAPPING": str(MAPPING_PATH),
        "TOOLCHAIN": str(TOOLCHAIN_PATH),
    })
    full_env.update(env or {})
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        env=full_env,
        cwd=str(cwd or REPO_ROOT),
        timeout=timeout,
    )
    return StepResult(proc, parse_github_output(output_path),
                      summary_path.read_text(encoding="utf-8"))


# --- `work` step harness ---------------------------------------------------
WORK_STEP = "Decide whether there is work"
WORK_STEP_OUTPUTS = {"moves", "closes", "all_rejected", "state_screen"}


def run_work_step(tmp_path, actions, moves_text="", *, mapping=None):
    """Run the shipped `work` step over an action plan and a ledger batch.

    `actions` is drain.py's out-actions document (a dict) or the raw text of
    one; `moves_text` is the out-moves file's content.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    blob = actions if isinstance(actions, str) else json.dumps(actions, indent=2)
    (tmp_path / "actions.json").write_text(blob, encoding="utf-8")
    (tmp_path / "moves.txt").write_text(moves_text, encoding="utf-8")
    env = {"MAPPING": str(mapping)} if mapping is not None else None
    return run_workflow_step(workflow_step_run(WORK_STEP), runner_temp=tmp_path, env=env)


def run_drain_then_work_step(tmp_path, issues, ledger_text, *, toolchain=None):
    """Drive the shipped `work` step with REAL drain.py output.

    The two are a contract: the step reads only fields drain.py writes. Feeding
    it a hand-built plan tests the step against an imagined producer, so every
    behavioural scenario goes through the real one and only the deliberately
    DEFECTIVE plans (which a correct drain cannot emit) are synthetic.
    """
    proc, moves_path, actions_path = run_drain(
        tmp_path / "drain", issues, ledger_text, toolchain=toolchain
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    actions = load_actions(actions_path)
    moves_text = moves_path.read_text(encoding="ascii")
    result = run_work_step(tmp_path / "step", actions, moves_text)
    return actions, moves_text, result


# --- SPEC 5.8: section state, the unconditional display witness ------------
#: Closed set of three in PRECEDENCE order, mirrored in mapping section_states.
SECTION_SEALED, SECTION_CAPPED, SECTION_OPEN = "sealed", "capped", "open"

#: SPEC 5.8 screen selection is a LOOKUP, not a predicate: the consumer maps a
#: value it was handed and hard-fails on an unmapped one. Encoded once here so
#: no test re-derives "what sealed means".
SCREEN_FOR_SECTION_STATE = {
    SECTION_SEALED: "SEALED",
    SECTION_CAPPED: "LOG_FULL",
    SECTION_OPEN: "",
}


def section_state_of(actions):
    """SPEC 5.8's field, failing with the whole document when it is absent.

    A bare KeyError would read as a harness bug; the missing field IS the
    finding, so it is reported as one.
    """
    assert "section" in actions, (
        "SPEC 5.8: the actions JSON carries no top-level `section` member. It is "
        "unconditional on every exit-0 drain — including an empty, all-duplicate "
        f"or nothing-admissible batch. Got keys: {sorted(actions)}"
    )
    section = actions["section"]
    assert isinstance(section, dict) and "state" in section, (
        f"SPEC 5.8: `section` must be an object carrying `state`, got {section!r}"
    )
    return section["state"]


class _NoReason:
    """Sentinel: emit a post_push entry with NO `reason` key at all."""

    def __repr__(self):  # pragma: no cover - only rendered on failure
        return "<no reason field>"


#: Distinct from `reason: null` — one omits the key, the other sets it to null.
#: jq's `join` renders BOTH as the empty string, which is why the enum guard
#: uses `tojson`; the two cases therefore need separate fixtures.
NO_REASON_FIELD = _NoReason()

#: drain.py's reason -> action derivation, mirrored so synthetic plans are
#: well-formed in every dimension EXCEPT the one a given test deforms.
ACTION_FOR_REASON = {
    "applied": "close-applied",
    "duplicate": "close-duplicate",
    "grammar": "close-reject",
    "cooldown": "close-reject",
    "section-cap": "close-reject",
    "sealed": "close-reject",
}


#: Sentinel: emit an actions document with NO top-level `section` member.
NO_SECTION_FIELD = object()


def close_plan(*entries, section=SECTION_OPEN):
    """A synthetic post_push plan: `close_plan((1, "sealed"), (2, "grammar"))`.

    Only for plans a correct drain.py CANNOT emit — the defect cases the
    consumer's guards exist to refuse, and the combinations the drain's own
    ordering makes unreachable but the consumer defends against anyway.
    `section` carries the SPEC 5.8 state; pass NO_SECTION_FIELD to omit it.
    """
    post_push = []
    for issue, reason in entries:
        entry = {"issue": issue, "action": ACTION_FOR_REASON.get(reason, "close-reject"),
                 "message": None}
        if reason is not NO_REASON_FIELD:
            entry["reason"] = reason
        post_push.append(entry)
    plan = {"mapping_version": MAPPING_VERSION, "moves": [], "post_push": post_push}
    if section is not NO_SECTION_FIELD:
        plan["section"] = {"state": section}
    return plan


def _sortable(code):
    """Order codes deterministically even when one is absent or non-string."""
    return (code is None, str(code))


def reason_codes_of(actions):
    """The reason codes in a plan, as a sorted list (missing key -> None)."""
    return sorted((entry.get("reason") for entry in actions["post_push"]),
                  key=_sortable)


def assert_drain_plan_shape(actions, moves_text, *, reasons, applied, drained,
                            ledger_lines=None):
    """Assert a scenario IS the case its name claims, before asserting the verdict.

    Same discipline as assert_fixture_shape(): a scenario named "grammar-only"
    whose drain actually emitted `cooldown` would assert a different predicate
    than it advertises, and the step's output would look correct for the wrong
    reason. Pin the input first, then judge the output.
    """
    got = sorted({entry.get("reason") for entry in actions["post_push"]}, key=_sortable)
    want = sorted(set(reasons), key=_sortable)
    assert got == want, f"scenario reason codes: got {got}, claimed {want}"
    got_applied = len([e for e in actions["post_push"] if e.get("reason") == "applied"])
    assert got_applied == applied, (
        f"scenario applied closes: got {got_applied}, claimed {applied}"
    )
    got_drained = len([e for e in actions["post_push"] if e.get("reason") != "duplicate"])
    assert got_drained == drained, (
        f"scenario drained (non-duplicate) closes: got {got_drained}, claimed {drained}"
    )
    expected_lines = applied if ledger_lines is None else ledger_lines
    got_lines = len(moves_text.splitlines())
    assert got_lines == expected_lines, (
        f"scenario ledger lines: got {got_lines}, claimed {expected_lines}"
    )


# --- `encode` step harness -------------------------------------------------
ENCODE_STEP = "Encode the GIF through the budget ladder"

#: A stand-in for the pinned ffmpeg. It copies a prepared artifact into the
#: output path the step names, so the REAL budget.py renders the REAL verdict
#: over a REAL file and the shipped shell does the REAL branching. Only the
#: encoder — the one component a unit test cannot run — is replaced.
FFMPEG_STUB = '''#!/usr/bin/env python3
"""Deterministic ffmpeg stand-in driven by DOOM_STUB_ARTIFACTS (JSON list).

Rung N of the ladder gets artifact N; the last entry repeats for any further
rung, so a one-element list means "every rung produces this". The literal
"NONE" means "exit 0 without writing an output file".
"""
import json, os, pathlib, shutil, sys

sys.stdin.buffer.read()  # drain the pipe: `tail -c ... | ffmpeg` under
                         # `set -o pipefail` fails the step on SIGPIPE
counter = pathlib.Path(os.environ["DOOM_STUB_COUNTER"])
call = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(call + 1))
artifacts = json.loads(os.environ["DOOM_STUB_ARTIFACTS"])
source = artifacts[min(call, len(artifacts) - 1)]
if source != "NONE":
    shutil.copyfile(source, sys.argv[-1])
'''

NO_ARTIFACT = "NONE"


def run_encode_step(tmp_path, artifacts, *, cwd=None, capture_bytes=4096):
    """Run the shipped encode step with a stubbed encoder and the real gate.

    `artifacts` is a list of on-disk paths (or NO_ARTIFACT) — one per ladder
    rung, last entry repeating.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "capture.raw").write_bytes(b"\0" * capture_bytes)
    stub = tmp_path / "ffmpeg_stub.py"
    stub.write_text(FFMPEG_STUB, encoding="utf-8")
    stub.chmod(0o755)
    env = {
        "FFMPEG_BIN": str(stub),
        "FPS": "12",
        "WIDTH": "320",
        "HEIGHT": "200",
        "FRAME_BYTES": str(320 * 200 * 4),
        "DOOM_STUB_ARTIFACTS": json.dumps([str(a) for a in artifacts]),
        "DOOM_STUB_COUNTER": str(tmp_path / "stub_calls"),
    }
    return run_workflow_step(workflow_step_run(ENCODE_STEP),
                             runner_temp=tmp_path, env=env, cwd=cwd)


def stub_budget_sandbox(tmp_path, exit_code, stdout="{}"):
    """A cwd whose `game/scripts/budget.py` exits with an arbitrary code.

    The step invokes the gate by RELATIVE path, so a sandboxed cwd is how an
    exit outside budget.py's documented taxonomy can be exercised without
    touching the real gate (which owns that taxonomy and must not be edited to
    make a workflow test pass).
    """
    scripts = tmp_path / "game" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "budget.py").write_text(
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.exit({int(exit_code)})\n",
        encoding="utf-8",
    )
    return tmp_path


# --- Summarize step harness ------------------------------------------------
SUMMARIZE_STEP = "Summarize"
STATE_SWAP_STEP = "Swap in the SEALED or LOG_FULL guidance screen"


def run_summarize_step(tmp_path, **env):
    """Run the shipped Summarize step. Every input arrives through env, which
    is the workflow's own uniform rule (no `${{ }}` inside any run block)."""
    defaults = {
        "GITHUB_EVENT_NAME": "issues",
        "DRY_RUN": "false",
        "MOVES": "n/a",
        "CLOSES": "n/a",
        "RUNG": "n/a",
        "PIN_MISMATCH": "false",
        "ALL_REJECTED": "false",
        "STATE_SCREEN": "none",
        "BUDGET_FAILURE": "none",
        "SWAP_OUTCOME": "skipped",
    }
    defaults.update({key: str(value) for key, value in env.items()})
    return run_workflow_step(workflow_step_run(SUMMARIZE_STEP),
                             runner_temp=tmp_path, env=defaults)
