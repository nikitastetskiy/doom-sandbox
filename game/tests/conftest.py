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
README_PATH = REPO_ROOT / "README.md"
FIXTURES_DIR = GAME_DIR / "tests" / "fixtures"  # E2-owned; read-only for E3

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


def sparse_file(tmp_path, name, size):
    """Create a file of exactly `size` bytes without writing `size` bytes."""
    path = tmp_path / name
    with open(path, "wb") as fh:
        if size:
            fh.seek(size - 1)
            fh.write(b"\0")
    assert path.stat().st_size == size
    return path


# --- Drain helpers ---------------------------------------------------------
def make_issue(number, title, created_at, login="visitor"):
    """GitHub REST subset consumed by drain.py (issues are JSON files, never API)."""
    return {"number": number, "title": title, "created_at": created_at,
            "user": {"login": login}}


def run_drain(tmp_path, issues, ledger_text, *, mapping=MAPPING_PATH, extra_args=()):
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(issues), encoding="utf-8")
    ledger_path = tmp_path / "log.txt"
    ledger_path.write_text(ledger_text, encoding="ascii")
    moves_path = tmp_path / "moves.out"
    actions_path = tmp_path / "actions.json"
    proc = run_script(
        "drain.py",
        ["--issues", str(issues_path), "--ledger", str(ledger_path),
         "--mapping", str(mapping), "--out-moves", str(moves_path),
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
