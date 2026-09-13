#!/usr/bin/env python3
# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Test: Robot movement sequence with safety guard.

Executes a controlled sequence of movements with 1-second pauses.
Motors are ALWAYS stopped in the finally block.

Run with: python tests/test_robot.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectorcontrol.config import load_config
from vectorcontrol.connection import VectorConnection
from vectorcontrol.robot import VectorRobot
from vectorcontrol.safety import SafetyGuard

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PAUSE = 1.0  # seconds between actions


def run_sequence(vr: VectorRobot) -> None:
    """Execute the test movement sequence."""

    def step(label: str, func, *args, **kwargs):
        print(f"  → {label}")
        try:
            result = func(*args, **kwargs)
            time.sleep(PAUSE)
            return result
        except Exception as exc:
            print(f"    ⚠ Error: {exc}")
            raise

    # 1. Head up slightly
    step("Head up (10°)", vr.head_up, 10.0)

    # 2. Head down
    step("Head down (0°)", vr.head_down, 0.0)

    # 3. Lift up
    step("Lift up (0.3)", vr.lift_up, 0.3)

    # 4. Lift down
    step("Lift down (0.0)", vr.lift_down, 0.0)

    # 5. Say text
    step('Say "Hello, I am Vector"', vr.say, "Hello, I am Vector")

    # 6. Drive forward 50mm at 30mm/s
    step("Drive forward 50mm @ 30mm/s", vr.drive_forward, 50.0, 30.0)

    # 7. Stop
    step("Stop", vr.stop)

    # 8. Turn right 30° at 30deg/s
    step("Turn right 30° @ 30°/s", vr.turn_right, 30.0, 30.0)

    # 9. Stop
    step("Stop", vr.stop)

    print("\n  Sequence complete ✓")


def main() -> None:
    print("\n── Vector Robot Movement Test ──\n")

    try:
        config = load_config()
    except Exception as exc:
        print(f"Config error: {exc}")
        sys.exit(1)

    print(f"Robot : {config.name}  ({config.serial}  {config.ip})\n")

    try:
        with VectorConnection(config, timeout=15) as conn:
            print("Connected ✓\n")
            robot = conn.robot
            vr = VectorRobot(robot)

            with SafetyGuard(robot) as guard:
                try:
                    run_sequence(vr)
                except Exception as exc:
                    print(f"\n✗ Sequence aborted: {exc}")
                    logger.exception("Movement sequence failed")
                finally:
                    # SafetyGuard.__exit__ will stop motors, but also
                    # call stop() here for belt-and-suspenders clarity
                    print("\n  Stopping motors …")
                    vr.stop()

    except ConnectionError as exc:
        print(f"\nConnection failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        logger.exception("Unexpected error")
        sys.exit(1)

    print("Done ✓")


if __name__ == "__main__":
    main()