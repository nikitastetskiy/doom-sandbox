"""
@spec-handoff
@interface gamelog.section_is_sealed(header, *, engine, wad, mapping_version)
    -> bool. Keyword-only comparands, one per SPEC 5.9 sealing pin. There is
    deliberately NO `build` parameter: the signature is what makes "build is
    not a comparand" true by construction rather than by discipline.
    drain.py and apply_moves.py both call it and neither defines its own.
@behavior
    - Returns True iff any of the mapping's `sealing_pins` in the header
      disagrees with the supplied comparand. Those pins are exactly the
      replay's INPUTS (engine, wad, mapping); `build` is an artifact of
      COMPILING one of them, and the golden fixture shows two artifacts of the
      same input replaying identically
    - `build=` stays in the SPEC 5.2 header as provenance and is written by
      apply_moves.py from --engine-build-sha256, the hash of the binary the run
      actually executed. It is recorded, never compared
    - Both callers therefore read only COMMITTED values, so they cannot
      disagree by construction — which is the point, not a side effect
@edge-cases
    - A runner-image rotation moves the observed build hash while the committed
      pin lags: the section must stay open, no `new game` is demanded, and the
      next section opened by a rollover must not be sealed on arrival
    - Perturbing a non-pin header field (build, n) must NOT seal; perturbing
      any sealing pin MUST seal — asserted from the mapping, not from a list
      retyped here
@see game/SPEC.md 5.5/5.9 and 0.5; game/mapping/v1.json sealing_pins;
    game/scripts/gamelog.py, drain.py, apply_moves.py
"""

import ast
import json

import pytest

from conftest import (
    BUILD_HEX,
    ENGINE_HEX,
    MAPPING_PATH,
    MAPPING_VERSION,
    SCRIPTS_DIR,
    WAD_HEX,
    import_gamelog,
    ledger_line,
    load_actions,
    load_mapping,
    make_issue,
    make_section_text,
    make_toolchain,
    run_drain,
    run_script,
    section_header,
)

TS = "2026-08-03T12:00:00Z"

SEALING_PINS = load_mapping()["sealing_pins"]

#: The rotation: a second, equally valid binary built from the SAME pinned
#: commit by a rotated runner image. Distinct from BUILD_HEX by one property
#: only — the bytes of the compiler's output.
ROTATED_BUILD_HEX = "1a" * 32

#: Perturbations of the comparands, keyed by the header field they move.
PIN_PERTURBATION = {
    "engine": "99" * 20,
    "wad": "77" * 32,
    "mapping": MAPPING_VERSION + 1,
    "build": ROTATED_BUILD_HEX,
}


# --- SPEC 0.5: exactly one implementation site ------------------------------
HEADER_PIN_ATTRS = {"engine", "wad", "build", "mapping"}


def modules_comparing_a_header_pin():
    """Every game/scripts module that compares a parsed header's pin attribute.

    An AST walk rather than a text search: `header.engine != engine` and
    `h.engine == running` are the same duplication and no regex catches both
    without also catching prose. SPEC 0.5's only acceptable answer to "how many
    places implement this predicate" is one.
    """
    found = {}
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for side in [node.left, *node.comparators]:
                if (isinstance(side, ast.Attribute)
                        and side.attr in HEADER_PIN_ATTRS
                        and isinstance(side.value, ast.Name)):
                    hits.append(f"{side.value.id}.{side.attr} (line {node.lineno})")
        if hits:
            found[path.name] = hits
    return found


def test_only_one_module_compares_a_section_header_pin():
    """The livelock proves why one site is not a style preference.

    Two copies read different comparands: drain.py compared the header against
    game/toolchain.json, apply_moves.py against the binary observed at run
    time. With a rotated image and a lagging pin they disagree, the drain
    admits a reset, apply_moves opens the next section with the OBSERVED hash,
    and the next drain seals that fresh section against the COMMITTED one —
    one sealed-on-arrival section per reset, forever, in committed state.
    """
    found = modules_comparing_a_header_pin()
    assert set(found) == {"gamelog.py"}, (
        "SPEC 0.5: the sealing predicate has exactly one implementation site "
        f"(gamelog.py). Header-pin comparisons found in: {found}"
    )


def test_gamelog_exposes_the_sealing_predicate():
    gamelog = import_gamelog()
    assert hasattr(gamelog, "section_is_sealed"), (
        "SPEC 5.9: gamelog.py owns the sealing predicate and both callers use it"
    )


def test_both_callers_import_the_predicate_rather_than_redefining_it():
    """Named apart from the AST count above: a caller could stop comparing pins
    by delegating to a THIRD helper of its own, which satisfies the count and
    still is not one site."""
    for name in ("drain.py", "apply_moves.py"):
        source = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        assert "gamelog.section_is_sealed" in source, (
            f"{name} does not call gamelog.section_is_sealed — SPEC 5.9 requires "
            f"both callers to read the one predicate"
        )


# --- The predicate compares exactly the mapping's sealing pins --------------
def call_predicate(**overrides):
    """Evaluate the predicate against a header perturbed by `overrides`."""
    gamelog = import_gamelog()
    fields = {"n": 1, "engine": ENGINE_HEX, "build": BUILD_HEX, "wad": WAD_HEX,
              "mapping": MAPPING_VERSION}
    fields.update(overrides)
    header = gamelog.Header(**fields)
    return gamelog.section_is_sealed(
        header, engine=ENGINE_HEX, wad=WAD_HEX, mapping_version=MAPPING_VERSION
    )


def test_a_header_matching_every_comparand_is_not_sealed():
    assert call_predicate() is False


@pytest.mark.parametrize("pin", SEALING_PINS)
def test_moving_any_sealing_pin_seals_the_section(pin, ):
    """Driven from the mapping, so a pin added there without an implementation
    fails here rather than passing silently."""
    assert call_predicate(**{pin: PIN_PERTURBATION[pin]}) is True, pin


def test_moving_the_build_hash_alone_does_not_seal():
    """SPEC 5.9's whole finding in one assertion.

    Two binaries, one replay: the ubuntu-24.04 build did not reproduce the
    reference build from the same pinned commit, while the golden fixture's
    framebuffer digest reproduced byte-exact across two architectures and two
    clangs. Sealing on the binary seals on a property the replay does not have.
    """
    assert call_predicate(build=ROTATED_BUILD_HEX) is False


def test_the_section_number_is_not_a_determinism_pin():
    assert call_predicate(n=7) is False


def test_the_predicate_takes_no_build_comparand():
    """Signature-level, because a `build=` parameter that callers happen not to
    pass is one refactor away from being passed again."""
    import inspect

    gamelog = import_gamelog()
    parameters = inspect.signature(gamelog.section_is_sealed).parameters
    assert "build" not in parameters, (
        f"SPEC 5.9: `build` is provenance, never a comparand; got {list(parameters)}"
    )
    for name in SEALING_PINS:
        expected = "mapping_version" if name == "mapping" else name
        assert expected in parameters, (
            f"sealing pin {name!r} has no comparand parameter: {list(parameters)}"
        )


# --- The rotation, end to end through both callers --------------------------
def rotated_ledger(build=BUILD_HEX, n=1, entries=()):
    """A section header carrying `build`, with everything else at the defaults
    make_toolchain() agrees with."""
    header = section_header(n=n, engine=ENGINE_HEX, build=build, wad=WAD_HEX)
    return "\n".join([header, *entries]) + "\n"


def run_apply_moves(tmp_path, ledger_text, moves_text, *, observed_build,
                    committed_build=BUILD_HEX, stream_text="\n"):
    """apply_moves.py with the COMMITTED pins and a separately-supplied
    OBSERVED build hash — the exact divergence SPEC 5.9 removes."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger = tmp_path / "log.txt"
    ledger.write_text(ledger_text, encoding="ascii")
    moves = tmp_path / "moves.txt"
    moves.write_text(moves_text, encoding="ascii")
    stream = tmp_path / "stream.txt"
    stream.write_text(stream_text, encoding="ascii")
    toolchain = make_toolchain(tmp_path, engine=ENGINE_HEX, wad=WAD_HEX,
                              build=committed_build)
    proc = run_script("apply_moves.py", [
        "--ledger", str(ledger), "--moves", str(moves),
        "--mapping", str(MAPPING_PATH), "--toolchain", str(toolchain),
        "--engine-build-sha256", observed_build, "--stream", str(stream),
    ])
    return proc, ledger


def drain_state(tmp_path, issues, ledger_text):
    """The SPEC 5.8 state the drain reports for a ledger, plus its plan."""
    proc, moves_path, actions_path = run_drain(
        tmp_path, issues, ledger_text,
        toolchain=make_toolchain(tmp_path, engine=ENGINE_HEX, wad=WAD_HEX,
                                 build=BUILD_HEX),
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    actions = load_actions(actions_path)
    return actions["section"]["state"], actions, moves_path.read_text(encoding="ascii")


def test_the_drain_does_not_seal_a_section_whose_build_hash_rotated(tmp_path):
    ledger = rotated_ledger(build=ROTATED_BUILD_HEX,
                            entries=[ledger_line(TS, "old", "fire", 1, 5)])
    assert f"build={ROTATED_BUILD_HEX}" in ledger, "the fixture must carry the rotation"
    state, actions, moves_text = drain_state(
        tmp_path, [make_issue(20, "doom: fire", TS)], ledger
    )
    assert state == "open", actions
    assert moves_text.endswith("fire 1 #20\n"), (
        "an ordinary move must be admitted, not sealed-rejected"
    )


def test_apply_moves_appends_when_the_running_binary_rotated_under_it(tmp_path):
    """Exit 7 is rule 4's defense in depth. It must not fire on a rotation —
    that is a refusal to advance a section nothing is wrong with.

    Discriminating shape, deliberately: the section carries the COMMITTED hash
    (it opened before the rotation) and the binary running now is a different
    one. A fixture where the header and the observed hash agree passes against
    the old predicate just as readily and tests nothing.
    """
    ledger = rotated_ledger(build=BUILD_HEX)
    assert f"build={BUILD_HEX}" in ledger and BUILD_HEX != ROTATED_BUILD_HEX, (
        "the header must carry the committed hash and the runner a different one"
    )
    proc, ledger_path = run_apply_moves(
        tmp_path, ledger, f"{ledger_line(TS, 'p', 'fire', 1, 20)}\n",
        observed_build=ROTATED_BUILD_HEX, committed_build=BUILD_HEX,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert json.loads(proc.stdout.decode())["sealed"] is False
    assert "fire 1 #20" in ledger_path.read_text(encoding="ascii")


def test_apply_moves_appends_into_a_section_opened_by_a_rotated_binary(tmp_path):
    """The other side of the same rotation: the section was opened AFTER it, so
    the header carries the observed hash and the committed pin still lags."""
    ledger = rotated_ledger(build=ROTATED_BUILD_HEX)
    proc, ledger_path = run_apply_moves(
        tmp_path, ledger, f"{ledger_line(TS, 'p', 'fire', 1, 22)}\n",
        observed_build=ROTATED_BUILD_HEX, committed_build=BUILD_HEX,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "fire 1 #22" in ledger_path.read_text(encoding="ascii")


@pytest.mark.parametrize("pin", [p for p in SEALING_PINS if p != "mapping"])
def test_apply_moves_still_refuses_a_frame_move_into_a_genuinely_sealed_section(
    tmp_path, pin
):
    """The relaxation is scoped strictly to `build`: SPEC 5.5 rule 4 is intact
    for every pin that is actually a replay input."""
    header = section_header(n=1, engine=ENGINE_HEX, build=BUILD_HEX, wad=WAD_HEX)
    moved = header.replace(f"{pin}={ENGINE_HEX if pin == 'engine' else WAD_HEX}",
                           f"{pin}={PIN_PERTURBATION[pin]}")
    assert moved != header, f"the fixture did not actually move {pin}"
    proc, _ = run_apply_moves(
        tmp_path, moved + "\n", f"{ledger_line(TS, 'p', 'fire', 1, 20)}\n",
        observed_build=BUILD_HEX,
    )
    assert proc.returncode == 7, (proc.returncode, proc.stdout, proc.stderr)


def test_the_rollover_records_the_binary_that_ran_as_provenance(tmp_path):
    """`build=` stays in the header (SPEC 5.2's six fields are unchanged) and
    records WHICH binary produced this section's frames."""
    ledger = rotated_ledger(entries=[ledger_line(TS, "old", "fire", 1, 5)])
    proc, ledger_path = run_apply_moves(
        tmp_path, ledger, f"{ledger_line(TS, 'p', 'new-game', 1, 21)}\n",
        observed_build=ROTATED_BUILD_HEX,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    headers = [line for line in ledger_path.read_text(encoding="ascii").splitlines()
               if line.startswith("#section")]
    assert len(headers) == 2, headers
    assert f"build={ROTATED_BUILD_HEX}" in headers[1], (
        f"the new section must record the binary that ran: {headers[1]}"
    )


# --- The livelock: the two sites fed DIFFERENT values ------------------------
def test_a_rollover_under_a_rotated_image_does_not_seal_the_next_section(tmp_path):
    """The known-bad control for single-siteness, run as a behaviour.

    This is the ONLY shape that discriminates: a test in which both sites see
    the same comparand passes against two copies just as readily as against
    one. Here the drain reads the COMMITTED hash and apply_moves is handed the
    OBSERVED one, which is exactly the divergence a rotation creates.

    Pre-fix this cycle produces a section that is sealed on arrival, whose only
    admissible move is another reset, which opens another sealed section — in
    committed state, forever.
    """
    ledger = rotated_ledger(entries=[ledger_line(TS, "old", "fire", 1, 5)])

    # 1. The drain admits the rollover: the committed pins all agree.
    state, _, moves_text = drain_state(
        tmp_path / "drain1", [make_issue(30, "doom: new game", TS)], ledger
    )
    assert state == "open"
    assert moves_text.endswith("new-game 1 #30\n"), (
        "the rollover must actually land — a fixture that only claims to roll "
        f"over grades the naive implementation correct: {moves_text!r}"
    )

    # 2. apply_moves opens the next section under the ROTATED binary.
    proc, ledger_path = run_apply_moves(
        tmp_path / "apply", ledger, moves_text, observed_build=ROTATED_BUILD_HEX,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    rolled = ledger_path.read_text(encoding="ascii")
    assert f"build={ROTATED_BUILD_HEX}" in rolled, (
        "the fixture must actually diverge for this to test anything"
    )

    # 3. The next drain compares that fresh header against the COMMITTED hash.
    state, actions, moves_text = drain_state(
        tmp_path / "drain2", [make_issue(31, "doom: fire", TS)], rolled
    )
    assert state == "open", (
        "the section opened by the rollover is sealed on arrival — SPEC 5.9's "
        f"livelock: {actions}"
    )
    assert moves_text.endswith("fire 1 #31\n"), (
        "the only admissible move is another reset, which opens another sealed "
        "section: the livelock is closed"
    )


def test_two_consecutive_rollovers_under_a_rotated_image_stay_open(tmp_path):
    """One cycle can be a coincidence; the defect is that it never terminates."""
    ledger = rotated_ledger(entries=[ledger_line(TS, "old", "fire", 1, 5)])
    # A second rotation between the two cycles, so neither cycle can pass by the
    # observed hash happening to equal the previous section's. The timestamps
    # clear the SPEC 6 new-game cooldown: once the livelock is fixed the second
    # section is NOT sealed, so the cooldown applies to it — the very rule a
    # sealed section is exempt from (SPEC 5.5 rule 6). A fixture reusing one
    # timestamp fails against the correct implementation and passes against the
    # broken one.
    cycles = ((ROTATED_BUILD_HEX, "2026-08-03T12:00:00Z"),
              ("2b" * 32, "2026-08-03T13:00:00Z"))
    for cycle, (observed, created_at) in enumerate(cycles):
        state, _, moves_text = drain_state(
            tmp_path / f"drain{cycle}",
            [make_issue(40 + cycle, "doom: new game", created_at)], ledger,
        )
        assert state == "open", f"cycle {cycle} opened sealed"
        assert moves_text.endswith(f"new-game 1 #{40 + cycle}\n"), (
            f"cycle {cycle} rollover did not land: {moves_text!r}"
        )
        proc, ledger_path = run_apply_moves(
            tmp_path / f"apply{cycle}", ledger, moves_text, observed_build=observed,
        )
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        ledger = ledger_path.read_text(encoding="ascii")
        assert f"build={observed}" in ledger, f"cycle {cycle} did not roll over"
    state, actions, _ = drain_state(tmp_path / "final", [], ledger)
    assert state == "open", actions


def test_a_committed_pin_move_still_seals_end_to_end(tmp_path):
    """The fourth SPEC 5.9 failure class, still a game event: `engine`, `wad` or
    `mapping` moving in a default-branch commit seals, healed in band."""
    sealed_ledger = "\n".join([
        section_header(n=1, engine="99" * 20, build=BUILD_HEX, wad=WAD_HEX),
        ledger_line(TS, "old", "fire", 1, 5),
    ]) + "\n"
    state, actions, moves_text = drain_state(
        tmp_path, [make_issue(50, "doom: fire", TS)], sealed_ledger
    )
    assert state == "sealed", actions
    assert moves_text == "", "a frame-contributing move must not be admitted"
    reasons = {entry["reason"] for entry in actions["post_push"]}
    assert reasons == {"sealed"}, actions
