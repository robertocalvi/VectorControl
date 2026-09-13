#!/usr/bin/env python3
# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Test the Vector wake sequence end-to-end.

Usage (from VectorControl/ directory):
    .venv/bin/python tools/test_wake_sequence.py

Steps:
  1. Connect in observation mode
  2. Start wake sequence (non-blocking)
  3. Poll until AWAKE or failure (35 s timeout)
  4. Release control
  5. Disconnect
"""

from __future__ import annotations

import sys
import time
import logging
from pathlib import Path

# Ensure project root is on sys.path regardless of CWD
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_wake")

from vectorcontrol.vector_manager import VectorManager  # noqa: E402
from vectorcontrol.vector_state import VectorState       # noqa: E402

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
RESET = "\033[0m"
GREEN = "\033[92m"
RED   = "\033[91m"
AMBER = "\033[93m"
BOLD  = "\033[1m"
DIM   = "\033[2m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {AMBER}→{RESET} {msg}")


def step(n: int, msg: str) -> None:
    print(f"\n{BOLD}[{n}]{RESET} {msg}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"\n{BOLD}{'=' * 52}{RESET}")
    print(f"{BOLD}  Vector Wake Sequence Test{RESET}")
    print(f"{BOLD}{'=' * 52}{RESET}")

    mgr = VectorManager()

    # ── Step 1: Connect ────────────────────────────────────────────────
    step(1, "Connecting in observation mode (timeout=15 s)…")
    mgr.connect()
    state = mgr.state.state
    print(f"  State after connect: {BOLD}{state.value}{RESET}")

    if state == VectorState.ERROR:
        fail(f"Connection failed: {mgr.state.error}")
        return 1

    if state != VectorState.CONNECTED:
        fail(f"Unexpected state: {state.value!r}")
        return 1

    ok("Connected in observation mode")

    # ── Step 2: Start wake (non-blocking) ──────────────────────────────
    step(2, "Starting wake sequence (non-blocking, timeout=30 s)…")
    started = mgr.wake(timeout=30)

    if not started:
        fail(f"Wake not started — state: {mgr.state.state.value!r}")
        mgr.disconnect()
        return 1

    ok(f"Wake thread spawned (state: {BOLD}{mgr.state.state.value}{RESET})")

    # ── Step 3: Poll until AWAKE or failure ────────────────────────────
    step(3, "Polling for AWAKE state (up to 35 s)…")
    deadline = time.monotonic() + 35.0
    poll_ok = False

    while time.monotonic() < deadline:
        current = mgr.state.state
        elapsed = 35.0 - (deadline - time.monotonic())
        bar = "." * int(elapsed) + " " * (35 - int(elapsed))
        print(f"  [{bar}] {elapsed:5.1f} s  state={BOLD}{current.value}{RESET}    ", end="\r")
        sys.stdout.flush()

        if current == VectorState.AWAKE:
            print()  # clear \r line
            ok("Behavior control granted — Vector is AWAKE! 🤖")
            poll_ok = True
            break

        if current == VectorState.CONNECTED:
            print()
            fail(
                "Wake failed — returned to CONNECTED.\n"
                "  Hint: Vector may be sleeping deeply on the charger.\n"
                "  Touch Vector physically or say 'Hey Vector' to wake it, then retry."
            )
            mgr.disconnect()
            return 1

        if current == VectorState.ERROR:
            print()
            fail(f"Error during wake: {mgr.state.error}")
            mgr.disconnect()
            return 1

        time.sleep(0.25)
    else:
        print()
        fail("Timeout (35 s) waiting for AWAKE state")
        mgr.disconnect()
        return 1

    if not poll_ok:
        mgr.disconnect()
        return 1

    # ── Step 4: Release control ────────────────────────────────────────
    step(4, "Releasing behavior control…")
    mgr.release()
    ok(f"Released — state: {BOLD}{mgr.state.state.value}{RESET}")

    # ── Step 5: Disconnect ─────────────────────────────────────────────
    step(5, "Disconnecting…")
    mgr.disconnect()
    ok(f"Disconnected — final state: {BOLD}{mgr.state.state.value}{RESET}")

    print(f"\n{GREEN}{BOLD}All steps passed ✓{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())