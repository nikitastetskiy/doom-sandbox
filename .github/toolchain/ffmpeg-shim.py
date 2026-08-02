#!/usr/bin/env python3
"""``ffmpeg``-named PATH shim: capture doomreplay's raw BGRA frame stream.

doomreplay has no raw-dump mode.  ``DG_DrawFrame`` hard-builds an ``ffmpeg``
command line and ``popen()``s it, always declaring ``-pix_fmt bgra -vcodec
rawvideo -i -`` on the input side and an h264/yuv420p file on the output side.
The engine fork is kept pristine (Ei L3 provenance), so the supported way to
get the raw framebuffer out is to put an executable named ``ffmpeg`` earlier on
PATH than the real encoder: it ignores every argument except the last one (the
engine's output path) and copies stdin there verbatim.

The real, checksum-pinned ffmpeg is always invoked by ABSOLUTE PATH by the
workflow, so it can never be shadowed by this shim.  The GIF encode then
declares the input as ``-pix_fmt bgr0`` -- see game/toolchain.json
``encode.pix_fmt_warning``: the engine zeroes the alpha byte, so declaring
``bgra`` makes every pixel fully transparent and silently yields a blank GIF.

Streams in 1 MiB chunks: a 15 s tail at 35 fps / 640x400 BGRA is ~537 MB.

@see game/toolchain.json; game/tests/test_golden_frame.py (same contract);
    .yui-soul/knowledge/gotchas/doomreplay.md
"""

import sys

CHUNK = 1 << 20


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("ffmpeg-shim: refusing to run without an output path\n")
        return 2
    destination = sys.argv[-1]
    if destination.startswith("-"):
        sys.stderr.write("ffmpeg-shim: last argument is not an output path\n")
        return 2
    with open(destination, "wb") as sink:
        while True:
            chunk = sys.stdin.buffer.read(CHUNK)
            if not chunk:
                break
            sink.write(chunk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
