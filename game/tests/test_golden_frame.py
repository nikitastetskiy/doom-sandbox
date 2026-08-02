"""
@spec-handoff
@interface Golden-frame determinism test (RFC must_have 2): replays
    game/tests/fixtures/golden.stream through the engine binary named by env
    DOOM_ENGINE_BIN using golden.expected.json invocation.argv (argv[0] replaced
    by the binary path, "<raw-capture-path>" substituted with a temp file, cwd =
    repo root, stdin = /dev/null, an ffmpeg-named shim on PATH writes stdin to
    its final argument — per the E2 invocation note)
@behavior
    - Asserts: sha256(golden.stream) == fixture_sha256; captured bytes ==
      recorded_frames * frame_bytes; sha256(captured) == recorded_stream_sha256;
      sha256(last frame_bytes) == final_frame_sha256
    - SKIPS with an explicit reason ONLY while the engine binary or the E2
      fixture files are absent (E2/E7 run concurrently/later); it never
      silently passes
    - A present-but-schema-incomplete expected file is a FAILURE (cross-step
      contract mismatch), never a skip
@edge-cases
    - provisional_local status is informational only; E7 task 1 captures the
      canonical ubuntu-24.04 values into the same schema (plan D9) and this
      test re-verifies green unchanged
@see game/tests/fixtures/golden.expected.json; game/toolchain.json; RFC
    determinism guarantees; plan must_have 2
"""

import hashlib
import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import FIXTURES_DIR, REPO_ROOT

ENGINE_ENV = "DOOM_ENGINE_BIN"
GOLDEN_STREAM = FIXTURES_DIR / "golden.stream"
GOLDEN_EXPECTED = FIXTURES_DIR / "golden.expected.json"
REQUIRED_KEYS = {
    "fixture_sha256",
    "invocation",
    "recorded_frames",
    "frame_bytes",
    "recorded_stream_sha256",
    "final_frame_sha256",
}

FFMPEG_SHIM = """#!{python}
import sys
with open(sys.argv[-1], "wb") as fh:
    fh.write(sys.stdin.buffer.read())
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_golden_fixture_replay_reproduces_recorded_frame_count_and_checksums(tmp_path):
    missing = []
    engine = os.environ.get(ENGINE_ENV, "")
    if not engine or not os.path.isfile(engine):
        missing.append(f"engine binary (env {ENGINE_ENV} unset or not a file)")
    if not GOLDEN_STREAM.is_file():
        missing.append("game/tests/fixtures/golden.stream (E2)")
    if not GOLDEN_EXPECTED.is_file():
        missing.append("game/tests/fixtures/golden.expected.json (E2)")
    if missing:
        pytest.skip(
            "SKIP[golden-frame]: " + "; ".join(missing)
            + " — replay requires the E2 engine build/fixture; this test "
            "activates automatically once they are available and never "
            "silently passes"
        )

    expected = json.loads(GOLDEN_EXPECTED.read_text(encoding="utf-8"))
    missing_keys = sorted(REQUIRED_KEYS - set(expected))
    if missing_keys or "argv" not in expected.get("invocation", {}):
        pytest.fail(
            "golden.expected.json schema incomplete (missing "
            f"{missing_keys or ['invocation.argv']}) — cross-step contract "
            "mismatch with the E3 @spec-handoff, not a skip"
        )

    stream_bytes = GOLDEN_STREAM.read_bytes()
    assert _sha256(stream_bytes) == expected["fixture_sha256"], (
        "golden.stream does not match its recorded fixture_sha256"
    )

    # ffmpeg-named shim per the E2 invocation note: writes stdin to argv[-1]
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "ffmpeg"
    shim.write_text(FFMPEG_SHIM.format(python=sys.executable), encoding="ascii")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    capture = tmp_path / "capture.raw"
    argv = [
        engine if i == 0 else (str(capture) if a == "<raw-capture-path>" else a)
        for i, a in enumerate(expected["invocation"]["argv"])
    ]
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"engine replay failed rc={proc.returncode}: {proc.stderr[-2000:]!r}"
    )

    assert capture.is_file(), (
        "engine replay produced no raw capture at the substituted "
        "<raw-capture-path> — check the ffmpeg-shim invocation contract in "
        "golden.expected.json"
    )
    data = capture.read_bytes()
    frame_bytes = expected["frame_bytes"]
    assert len(data) == expected["recorded_frames"] * frame_bytes, (
        "captured stream size disagrees with recorded_frames * frame_bytes"
    )
    assert _sha256(data) == expected["recorded_stream_sha256"], (
        "recorded stream checksum mismatch — determinism violation"
    )
    assert _sha256(data[-frame_bytes:]) == expected["final_frame_sha256"], (
        "final-frame checksum mismatch — determinism violation (must_have 2)"
    )
