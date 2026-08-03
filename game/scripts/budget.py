#!/usr/bin/env python3
"""GIF publish gate and re-encode ladder (SPEC sections 12 and 12.1, RFC D7).

Publication requires **positive structural evidence** that the artifact is a
well-formed, non-degenerate GIF (SPEC 12.1).  The absence of a ceiling violation
proves nothing: a 0-byte file, a truncated file and a palette-collapsed file all
satisfy "not too large".  So the gate runs three ordered checks, and every
normative value it compares against is read at runtime from the mapping file
(``budget.floor_bytes``, ``budget.ceiling_bytes``, ``budget.ladder``):

  1. **Structural validity** -- positive property: the artifact is the
     *complete* output of a GIF writer.  Evidence: the file exists, is
     non-empty, **begins** with the ``GIF89a`` magic and **ends** with the
     ``0x3B`` trailer.  Head and tail, because they establish different halves
     of the property and neither substitutes for the other -- the magic proves
     a writer started, the trailer is the last byte the muxer emits and so
     proves one finished.  Head-only evidence is structurally incapable of
     detecting truncation: truncation removes bytes from the *end*, and no care
     in reading the header can speak to any byte after offset 5.  Enforced here
     **independently and unconditionally**, before any size verdict, even though
     the workflow checks it too: assuming validity because an upstream gate
     exists is the antipattern 12.1 makes normative against (same
     defense-in-depth precedent as SPEC 5.5 rule 4).

     Residual it does **not** establish (SPEC 0.3): the block chain between the
     two ends.  Truncation landing exactly on a ``0x3B`` byte (~0.3 % of offsets
     in a reference L0 artifact) and mid-file corruption both still pass.
     Closing them needs a decoder in the publish gate, rejected as
     disproportionate.  Semantic degeneracy (palette collapse) is deliberately
     the floor's job, not this step's.
  2. **Floor** -- ``size > floor_bytes``.  The floor is **exclusive** while the
     ceiling is **inclusive**; the asymmetry is deliberate, not an oversight.
  3. **Ceiling / ladder** -- ``size <= ceiling_bytes``, else descend a rung.

Neither hard failure descends the ladder.  The ladder exists to make oversized
output smaller; descending on an undersized or malformed artifact makes it
smaller still, which cannot repair it and merely burns encodes.

The two failure integers are separate because they mean different things to an
operator: **13 = the encoder emitted garbage or the wrong file entirely** (a
pipeline or toolchain fault), **12 = the encoder emitted a well-formed but
degenerate clip** (a palette or ``pix_fmt`` fault).  Different first debugging
step.  Structural validity is orthogonal to size, which is why 13 is not folded
into 12: a *large* malformed artifact -- a truncated GIF, a PNG, an HTML error
page saved under a ``.gif`` name -- clears both the floor and the ceiling and
would otherwise publish.

A nonexistent ``--file`` path stays a usage error (exit 2): that is a malformed
*invocation*, not a malformed *artifact*.

**Only ``--file`` is a publication path.**  ``--size`` asserts a byte count with
no artifact behind it, so step 1 has nothing to read -- structural evidence is
not skipped there, it is *unavailable*.  ``--size`` is a tuning and diagnostic
entry point and its exit code is a **size verdict only**, which is why
``--size 0`` yields 12 while a 0-byte *file* yields 13: two different questions.

Usage: budget.py --mapping PATH --rung LEVEL (--size BYTES | --file PATH)
Exit codes: 0 publish / 2 usage / 10 over ceiling, re-encode at "next" /
            11 over ceiling at the last rung: hard fail, no publish /
            12 at or below the floor: hard fail, no publish, no descent /
            13 structurally invalid artifact: hard fail, no publish, no descent

@see game/SPEC.md sections 12 and 12.1; RFC D7; game/mapping/v1.json budget
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import gamelog

EXIT_PUBLISH = 0
EXIT_USAGE = 2
EXIT_REENCODE = 10
EXIT_HARD_FAIL = 11
EXIT_FLOOR = 12
EXIT_STRUCTURE = 13

REASON_STRUCTURE = "structure"
REASON_FLOOR = "floor"
REASON_CEILING = "ceiling"


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def _usage(message: str) -> int:
    sys.stderr.write(f"budget: {message}\n")
    return EXIT_USAGE


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--mapping", default=str(gamelog.DEFAULT_MAPPING_PATH))
    parser.add_argument("--rung", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--size", default=None)
    source.add_argument("--file", default=None)
    args = parser.parse_args(argv)

    mapping_path = Path(args.mapping)
    if not mapping_path.is_file():
        return _usage("mapping file not found")
    try:
        mapping = gamelog.load_mapping(mapping_path)
        budget = mapping["budget"]
        ceiling = int(budget["ceiling_bytes"])
        floor = int(budget["floor_bytes"])
        ladder = list(budget["ladder"])
        # SPEC 12.1: the structural literals are authored once, in the mapping,
        # and read at runtime -- never repeated in the script or the workflow.
        structure = budget["structure"]
        magic = bytes.fromhex(structure["magic_hex"])
        trailer = bytes.fromhex(structure["trailer_hex"])
    except (OSError, ValueError, KeyError, TypeError):
        return _usage("mapping file has no usable budget section")
    if not magic or not trailer:
        return _usage("mapping budget.structure carries an empty magic or trailer")

    def verdict(payload: dict) -> None:
        """Every verdict reports the floor alongside the ceiling (SPEC 12.1)."""
        _emit({"rung": args.rung, "ceiling": ceiling, "floor": floor, **payload})

    levels = [entry["level"] for entry in ladder]
    if args.rung not in levels:
        return _usage("unknown ladder rung")
    index = levels.index(args.rung)

    if args.size is not None:
        try:
            size = int(args.size)
        except ValueError:
            return _usage("--size must be an integer")
        if size < 0:
            return _usage("--size must not be negative")
    else:
        candidate = Path(args.file)
        # A missing path is a malformed INVOCATION, not a malformed artifact.
        if not candidate.is_file():
            return _usage("--file does not exist")
        try:
            size = candidate.stat().st_size
            head = tail = b""
            if size:
                with open(candidate, "rb") as stream:
                    head = stream.read(len(magic))
                    stream.seek(max(0, size - len(trailer)))
                    tail = stream.read(len(trailer))
        except OSError:
            return _usage("--file is unreadable")

        # SPEC 12.1 gate step 1, before any size verdict. Orthogonal to size: a
        # 1.5 MB non-GIF clears both the floor and the ceiling, and a truncated
        # GIF keeps its header, so the tail is the only evidence that catches it.
        if size == 0 or head != magic or tail != trailer:
            verdict({"publish": False, "size": size, "hard_fail": True,
                     "next": None, "reason": REASON_STRUCTURE})
            return EXIT_STRUCTURE

    # SPEC 12.1 gate step 2. Exclusive, unlike the inclusive ceiling below: at
    # or under the floor the encode is broken, not mis-tuned, so there is no
    # rung to descend to -- a smaller re-encode cannot repair a collapse.
    if size <= floor:
        verdict({"publish": False, "size": size, "hard_fail": True,
                 "next": None, "reason": REASON_FLOOR})
        return EXIT_FLOOR

    # SPEC 12.1 gate step 3.
    if size <= ceiling:
        verdict({"publish": True, "size": size, "hard_fail": False,
                 "next": None, "reason": None})
        return EXIT_PUBLISH

    if index + 1 < len(ladder):
        verdict({"publish": False, "size": size, "hard_fail": False,
                 "next": ladder[index + 1], "reason": None})
        return EXIT_REENCODE

    verdict({"publish": False, "size": size, "hard_fail": True,
             "next": None, "reason": REASON_CEILING})
    return EXIT_HARD_FAIL


if __name__ == "__main__":
    sys.exit(main())
