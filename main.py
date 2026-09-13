#!/usr/bin/env python3
# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""VectorControl - Terminal Remote Control

WASD + arrow key remote control for Anki Vector using curses.
Motors are ALWAYS stopped on quit, Ctrl+C, or any exception.

Run with: python main.py
"""

from __future__ import annotations

import curses
import logging
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from vectorcontrol.config import load_config
from vectorcontrol.connection import VectorConnection
from vectorcontrol.safety import emergency_stop, install_signal_handlers

logging.basicConfig(
    filename="/tmp/vectorcontrol_main.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Speed constants (all conservative)
# ---------------------------------------------------------------------------
DRIVE_SPEED = 50.0      # mm/s — forward/backward wheel speed
TURN_SPEED_L = -30.0    # mm/s — left wheel for turning right
TURN_SPEED_R = 30.0     # mm/s — right wheel for turning right
HEAD_STEP = 5.0         # degrees per key press
LIFT_STEP = 0.1         # normalized units per key press

HEAD_MIN = -22.0
HEAD_MAX = 44.5
LIFT_MIN = 0.0
LIFT_MAX = 1.0

# ---------------------------------------------------------------------------
# Key codes (curses)
# ---------------------------------------------------------------------------
KEY_W = ord("w")
KEY_S = ord("s")
KEY_A = ord("a")
KEY_D = ord("d")
KEY_R = ord("r")
KEY_F = ord("f")
KEY_Q = ord("q")
KEY_SPACE = ord(" ")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class RobotState:
    def __init__(self) -> None:
        self.head_angle: float = 0.0
        self.lift_height: float = 0.0
        self.battery_volts: str = "N/A"
        self.battery_level: str = "N/A"
        self.is_charging: str = "N/A"
        self.moving: str = "stopped"
        self.last_key: str = "—"
        self.error: str = ""


# ---------------------------------------------------------------------------
# UI rendering
# ---------------------------------------------------------------------------
def render(stdscr: curses.window, state: RobotState) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    lines = [
        "╔══════════════════════════════════════╗",
        "║      VectorControl - Remote Control  ║",
        "╠══════════════════════════════════════╣",
        f"║  Robot state: {state.moving:<22} ║",
        f"║  Head angle : {state.head_angle:>+6.1f}°                 ║",
        f"║  Lift height: {state.lift_height:>5.2f}                   ║",
        f"║  Battery    : {state.battery_level!s:<5} ({state.battery_volts})         ║",
        f"║  Charging   : {state.is_charging!s:<24} ║",
        f"║  Last key   : {state.last_key:<23} ║",
        "╠══════════════════════════════════════╣",
        "║  W/S   Drive fwd/back               ║",
        "║  A/D   Turn left/right              ║",
        "║  ↑/↓   Head up/down                 ║",
        "║  R/F   Lift up/down                 ║",
        "║  SPACE Emergency stop               ║",
        "║  Q     Quit                         ║",
        "╚══════════════════════════════════════╝",
    ]

    if state.error:
        lines.append(f"  ⚠  {state.error}")

    for i, line in enumerate(lines):
        if i < h and len(line) < w:
            try:
                stdscr.addstr(i, 0, line)
            except curses.error:
                pass

    stdscr.refresh()


# ---------------------------------------------------------------------------
# Control loop
# ---------------------------------------------------------------------------
def control_loop(stdscr: curses.window, conn: VectorConnection) -> None:
    robot = conn.robot
    state = RobotState()

    # Curses setup
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.nodelay(True)   # non-blocking getch
    curses.curs_set(0)

    # Initial battery read
    try:
        batt = robot.get_battery_state()
        volts = getattr(batt, "battery_volts", None)
        state.battery_volts = f"{volts:.2f}V" if isinstance(volts, float) else "N/A"
        state.battery_level = str(getattr(batt, "battery_level", "N/A"))
        state.is_charging = str(getattr(batt, "is_charging", "N/A"))
    except Exception as exc:
        logger.debug("Initial battery read failed: %s", exc)

    last_battery_check = time.monotonic()
    BATTERY_INTERVAL = 30.0  # seconds

    running = True
    while running:
        key = stdscr.getch()

        if key == KEY_Q:
            state.last_key = "Q (quit)"
            state.moving = "stopping…"
            render(stdscr, state)
            break

        elif key == KEY_SPACE:
            state.last_key = "SPACE (e-stop)"
            state.moving = "EMERGENCY STOP"
            try:
                robot.motors.set_wheel_speeds(0, 0)
            except Exception as exc:
                logger.warning("e-stop set_wheel_speeds error: %s", exc)
            try:
                robot.motors.stop_all_motors()
            except Exception as exc:
                logger.warning("e-stop stop_all_motors error: %s", exc)

        elif key == KEY_W:
            state.last_key = "W (forward)"
            state.moving = "forward"
            try:
                robot.motors.set_wheel_speeds(DRIVE_SPEED, DRIVE_SPEED)
            except Exception as exc:
                state.error = f"drive fwd: {exc}"
                logger.error("drive forward error: %s", exc)

        elif key == KEY_S:
            state.last_key = "S (backward)"
            state.moving = "backward"
            try:
                robot.motors.set_wheel_speeds(-DRIVE_SPEED, -DRIVE_SPEED)
            except Exception as exc:
                state.error = f"drive back: {exc}"
                logger.error("drive backward error: %s", exc)

        elif key == KEY_A:
            state.last_key = "A (turn left)"
            state.moving = "turning left"
            try:
                robot.motors.set_wheel_speeds(-TURN_SPEED_R, TURN_SPEED_R)
            except Exception as exc:
                state.error = f"turn left: {exc}"
                logger.error("turn left error: %s", exc)

        elif key == KEY_D:
            state.last_key = "D (turn right)"
            state.moving = "turning right"
            try:
                robot.motors.set_wheel_speeds(TURN_SPEED_R, -TURN_SPEED_R)
            except Exception as exc:
                state.error = f"turn right: {exc}"
                logger.error("turn right error: %s", exc)

        elif key == curses.KEY_UP:
            state.last_key = "↑ (head up)"
            state.head_angle = min(state.head_angle + HEAD_STEP, HEAD_MAX)
            try:
                from anki_vector.util import degrees as deg
                robot.motors.set_head_angle(deg(state.head_angle))
            except Exception as exc:
                state.error = f"head up: {exc}"
                logger.error("head up error: %s", exc)

        elif key == curses.KEY_DOWN:
            state.last_key = "↓ (head down)"
            state.head_angle = max(state.head_angle - HEAD_STEP, HEAD_MIN)
            try:
                from anki_vector.util import degrees as deg
                robot.motors.set_head_angle(deg(state.head_angle))
            except Exception as exc:
                state.error = f"head down: {exc}"
                logger.error("head down error: %s", exc)

        elif key == KEY_R:
            state.last_key = "R (lift up)"
            state.lift_height = min(state.lift_height + LIFT_STEP, LIFT_MAX)
            try:
                robot.motors.set_lift_height(state.lift_height)
            except Exception as exc:
                state.error = f"lift up: {exc}"
                logger.error("lift up error: %s", exc)

        elif key == KEY_F:
            state.last_key = "F (lift down)"
            state.lift_height = max(state.lift_height - LIFT_STEP, LIFT_MIN)
            try:
                robot.motors.set_lift_height(state.lift_height)
            except Exception as exc:
                state.error = f"lift down: {exc}"
                logger.error("lift down error: %s", exc)

        elif key == curses.ERR:
            # No key pressed — if moving via WASD, stop (released key)
            # Only reset "moving" display; wheels already set to 0 on next loop
            pass

        # Periodically refresh battery
        now = time.monotonic()
        if now - last_battery_check >= BATTERY_INTERVAL:
            last_battery_check = now
            try:
                batt = robot.get_battery_state()
                volts = getattr(batt, "battery_volts", None)
                state.battery_volts = f"{volts:.2f}V" if isinstance(volts, float) else "N/A"
                state.battery_level = str(getattr(batt, "battery_level", "N/A"))
                state.is_charging = str(getattr(batt, "is_charging", "N/A"))
            except Exception as exc:
                logger.debug("Battery refresh failed: %s", exc)

        render(stdscr, state)
        time.sleep(0.05)  # 20 Hz loop

    # Always stop on exit
    try:
        robot.motors.set_wheel_speeds(0, 0)
    except Exception:
        pass
    try:
        robot.motors.stop_all_motors()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        config = load_config()
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {config.name} ({config.serial} @ {config.ip}) …")

    try:
        with VectorConnection(config, timeout=15) as conn:
            install_signal_handlers(conn.robot)
            print("Connected. Starting remote control … (Q to quit)")
            time.sleep(0.5)
            curses.wrapper(control_loop, conn)
    except ConnectionError as exc:
        print(f"\nConnection failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted — motors stopped.")
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        logger.exception("Unexpected error in main")
        sys.exit(1)

    print("Remote control exited. Robot stopped.")


if __name__ == "__main__":
    main()