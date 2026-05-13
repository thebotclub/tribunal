"""Tribunal local daemon — FastAPI app served on http://localhost:8088.

Status (v3-pivot/week-1): stub. The real daemon lands Week 3 of the v3
execution plan, when the Claude Code adapter is wired in end-to-end. At
that point this module gains:

- FastAPI app with two endpoints:
    * POST /v1/events  — adapters POST normalised events here
    * GET  /v1/events  — local dashboard reads events from here
- SQLite-backed local event queue
- Static dashboard mounted at /
- Background batcher that ships events to Cloudflare when cloud mode is on

This stub exists today so that:

1. ``tribunal --help`` can advertise the ``serve`` subcommand without a
   late-bound import failing.
2. CI can run ``python -m tribunal.daemon --check`` to confirm the
   skeleton imports cleanly on the supported Python matrix.
"""

from __future__ import annotations

import sys
from typing import NoReturn

# The default port chosen for the local daemon. Keep aligned with
# documentation in README.md and the marketing site copy.
DEFAULT_PORT = 8088
DEFAULT_HOST = "127.0.0.1"


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> NoReturn:
    """Start the local Tribunal daemon. Not yet implemented."""
    raise NotImplementedError(
        "tribunal.daemon.serve() is not implemented in 2.0.x. "
        f"Targeted for v3 alpha (Week 3 of the v3 execution plan). "
        f"Planned bind: {host}:{port}."
    )


def _main(argv: list[str]) -> int:
    if "--check" in argv:
        # Smoke test: did this module import cleanly?
        print(f"tribunal.daemon scaffold OK (target {DEFAULT_HOST}:{DEFAULT_PORT})")
        return 0
    print(
        "tribunal.daemon is a v3 scaffold. Run `tribunal serve` once v3 ships.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
