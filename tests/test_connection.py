#!/usr/bin/env python3
# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Test: Connect to Vector and print robot information.

No motors are moved. Safe to run anytime.

Run with: python tests/test_connection.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make the project root importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from vectorcontrol.config import load_config
from vectorcontrol.connection import VectorConnection

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    print("\n── Vector Connection Test ──\n")

    try:
        config = load_config()
    except Exception as exc:
        print(f"Config error: {exc}")
        sys.exit(1)

    print(f"Robot : {config.name}")
    print(f"Serial: {config.serial}")
    print(f"IP    : {config.ip}")
    print()

    try:
        with VectorConnection(config, timeout=15) as conn:
            robot = conn.robot
            print("Connected ✓\n")

            # Firmware / version
            try:
                version = robot.get_version_state()
                print(f"Firmware  : {getattr(version, 'os_version', 'N/A')}")
                print(f"Engine ID : {getattr(version, 'engine_build_id', 'N/A')}")
            except Exception as exc:
                print(f"Version info unavailable: {exc}")

            # Battery
            try:
                battery = robot.get_battery_state()
                level = getattr(battery, "battery_level", "N/A")
                volts = getattr(battery, "battery_volts", "N/A")
                charging = getattr(battery, "is_charging", "N/A")
                on_charger = getattr(battery, "is_on_charger_platform", "N/A")

                volts_str = f"{volts:.2f}V" if isinstance(volts, float) else str(volts)
                print(f"Battery   : level={level}  volts={volts_str}")
                print(f"Charging  : {charging}  on_charger={on_charger}")
            except Exception as exc:
                print(f"Battery info unavailable: {exc}")

            print("\nDisconnecting …")

    except ConnectionError as exc:
        print(f"\nConnection failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        logger.exception("Unexpected error during connection test")
        sys.exit(1)

    print("Done ✓")


if __name__ == "__main__":
    main()