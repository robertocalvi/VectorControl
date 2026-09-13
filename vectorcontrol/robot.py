# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""VectorRobot - high-level command interface for Anki Vector.

All speed values are conservative and well within safe limits.
Uses anki_vector.util helpers for unit conversions.
"""

from __future__ import annotations

import logging
from typing import Any

import anki_vector
from anki_vector.util import degrees, distance_mm, speed_mmps

logger = logging.getLogger(__name__)

# Safety limits
_MAX_DRIVE_SPEED_MMPS = 100.0
_MAX_TURN_SPEED_DEGPS = 100.0
_DEFAULT_DRIVE_SPEED = 30.0
_DEFAULT_TURN_SPEED = 30.0


class VectorRobot:
    """High-level robot command interface.

    Wraps a connected anki_vector.Robot with safe, named methods.
    All movement commands use conservative default speeds.

    Usage::

        with VectorConnection() as conn:
            robot = VectorRobot(conn.robot)
            robot.say("Hello!")
            robot.drive_forward(50)
    """

    def __init__(self, robot: anki_vector.Robot) -> None:
        """
        Args:
            robot: An already-connected anki_vector.Robot instance.
        """
        self._robot = robot

    # ------------------------------------------------------------------
    # Head control
    # ------------------------------------------------------------------

    def head_up(self, angle_deg: float = 10.0) -> Any:
        """Tilt head upward by angle_deg from current position.

        Args:
            angle_deg: Target head angle in degrees (clamped to robot limits).

        Returns:
            SDK action result.
        """
        logger.debug("head_up(angle_deg=%s)", angle_deg)
        return self._robot.behavior.set_head_angle(degrees(angle_deg))

    def head_down(self, angle_deg: float = 0.0) -> Any:
        """Tilt head downward to angle_deg.

        Args:
            angle_deg: Target head angle in degrees (0 = looking forward/down).

        Returns:
            SDK action result.
        """
        logger.debug("head_down(angle_deg=%s)", angle_deg)
        return self._robot.behavior.set_head_angle(degrees(angle_deg))

    # ------------------------------------------------------------------
    # Lift control
    # ------------------------------------------------------------------

    def lift_up(self, height: float = 0.5) -> Any:
        """Raise the lift to height (0.0 = lowest, 1.0 = highest).

        Args:
            height: Normalized lift height [0.0 – 1.0].

        Returns:
            SDK action result.
        """
        height = max(0.0, min(1.0, height))
        logger.debug("lift_up(height=%s)", height)
        return self._robot.behavior.set_lift_height(height)

    def lift_down(self, height: float = 0.0) -> Any:
        """Lower the lift to height (0.0 = lowest, 1.0 = highest).

        Args:
            height: Normalized lift height [0.0 – 1.0].

        Returns:
            SDK action result.
        """
        height = max(0.0, min(1.0, height))
        logger.debug("lift_down(height=%s)", height)
        return self._robot.behavior.set_lift_height(height)

    # ------------------------------------------------------------------
    # Drive commands
    # ------------------------------------------------------------------

    def drive_forward(
        self,
        distance_mm_val: float = 50.0,
        speed_mmps_val: float = _DEFAULT_DRIVE_SPEED,
    ) -> Any:
        """Drive straight forward.

        Args:
            distance_mm_val: Distance to travel in mm.
            speed_mmps_val: Speed in mm/s (capped at 100 mm/s).

        Returns:
            SDK action result.
        """
        speed_mmps_val = min(abs(speed_mmps_val), _MAX_DRIVE_SPEED_MMPS)
        logger.debug("drive_forward(distance=%smm, speed=%smm/s)", distance_mm_val, speed_mmps_val)
        return self._robot.behavior.drive_straight(
            distance_mm(distance_mm_val),
            speed_mmps(speed_mmps_val),
        )

    def drive_backward(
        self,
        distance_mm_val: float = 50.0,
        speed_mmps_val: float = _DEFAULT_DRIVE_SPEED,
    ) -> Any:
        """Drive straight backward.

        Args:
            distance_mm_val: Distance to travel in mm.
            speed_mmps_val: Speed in mm/s (capped at 100 mm/s).

        Returns:
            SDK action result.
        """
        speed_mmps_val = min(abs(speed_mmps_val), _MAX_DRIVE_SPEED_MMPS)
        logger.debug("drive_backward(distance=%smm, speed=%smm/s)", distance_mm_val, speed_mmps_val)
        return self._robot.behavior.drive_straight(
            distance_mm(-distance_mm_val),
            speed_mmps(speed_mmps_val),
        )

    def turn_left(
        self,
        angle_deg: float = 30.0,
        speed_degps: float = _DEFAULT_TURN_SPEED,
    ) -> Any:
        """Turn left (counter-clockwise) by angle_deg.

        Args:
            angle_deg: Angle to turn in degrees.
            speed_degps: Angular speed in deg/s (capped at 100 deg/s).

        Returns:
            SDK action result.
        """
        speed_degps = min(abs(speed_degps), _MAX_TURN_SPEED_DEGPS)
        logger.debug("turn_left(angle=%sdeg, speed=%sdeg/s)", angle_deg, speed_degps)
        return self._robot.behavior.turn_in_place(
            degrees(angle_deg),
            speed=degrees(speed_degps),
        )

    def turn_right(
        self,
        angle_deg: float = 30.0,
        speed_degps: float = _DEFAULT_TURN_SPEED,
    ) -> Any:
        """Turn right (clockwise) by angle_deg.

        Args:
            angle_deg: Angle to turn in degrees.
            speed_degps: Angular speed in deg/s (capped at 100 deg/s).

        Returns:
            SDK action result.
        """
        speed_degps = min(abs(speed_degps), _MAX_TURN_SPEED_DEGPS)
        logger.debug("turn_right(angle=%sdeg, speed=%sdeg/s)", angle_deg, speed_degps)
        return self._robot.behavior.turn_in_place(
            degrees(-angle_deg),
            speed=degrees(speed_degps),
        )

    # ------------------------------------------------------------------
    # Speech
    # ------------------------------------------------------------------

    def say(self, text: str) -> Any:
        """Make the robot speak text.

        Args:
            text: Text to synthesize and play.

        Returns:
            SDK action result, or None if say_text is unavailable.
        """
        logger.debug("say(%r)", text)
        try:
            return self._robot.behavior.say_text(text)
        except AttributeError:
            logger.warning("say_text not available on this SDK version — skipping")
            return None

    # ------------------------------------------------------------------
    # Motor control
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop all motors immediately."""
        logger.debug("stop()")
        try:
            self._robot.motors.set_wheel_speeds(0, 0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("set_wheel_speeds(0,0) error: %s", exc)
        try:
            self._robot.motors.stop_all_motors()
        except Exception as exc:  # noqa: BLE001
            logger.debug("stop_all_motors error: %s", exc)

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def get_battery_info(self) -> dict[str, Any]:
        """Return battery state information.

        Returns:
            Dict with keys: battery_level, battery_volts, is_charging, is_on_charger.
        """
        state = self._robot.get_battery_state()
        return {
            "battery_level": getattr(state, "battery_level", None),
            "battery_volts": getattr(state, "battery_volts", None),
            "is_charging": getattr(state, "is_charging", None),
            "is_on_charger_platform": getattr(state, "is_on_charger_platform", None),
        }

    def get_robot_info(self) -> dict[str, Any]:
        """Return robot version and identity information.

        Returns:
            Dict with keys: serial, name, version.
        """
        version = self._robot.get_version_state()
        return {
            "serial": getattr(self._robot, "serial", None),
            "name": getattr(self._robot, "name", None),
            "os_version": getattr(version, "os_version", None),
            "engine_build_id": getattr(version, "engine_build_id", None),
        }