# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Safety utilities for VectorControl.

Provides emergency stop, signal handling, and a SafetyGuard context manager
that guarantees motors are stopped on any exception or clean exit.
"""

from __future__ import annotations

import logging
import signal
import types
from contextlib import contextmanager
from typing import Any, Callable

import anki_vector

logger = logging.getLogger(__name__)


def emergency_stop(robot: anki_vector.Robot) -> None:
    """Stop all motors immediately.

    Attempts multiple motor-stop paths so at least one succeeds even
    if the robot is in an unusual state.

    Args:
        robot: Connected anki_vector.Robot instance.
    """
    logger.warning("Emergency stop triggered")
    errors: list[str] = []

    try:
        robot.motors.set_wheel_speeds(0, 0)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"set_wheel_speeds: {exc}")

    try:
        robot.motors.stop_all_motors()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"stop_all_motors: {exc}")

    if errors:
        logger.debug("Emergency stop partial errors (non-fatal): %s", "; ".join(errors))


def safe_execute(robot: anki_vector.Robot, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a robot command safely; emergency-stop on any error.

    Args:
        robot: Connected anki_vector.Robot instance.
        func: Callable to execute.
        *args: Positional arguments forwarded to func.
        **kwargs: Keyword arguments forwarded to func.

    Returns:
        Whatever func returns.

    Raises:
        Re-raises the original exception after stopping motors.
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.error("Error during %s: %s — triggering emergency stop", getattr(func, "__name__", repr(func)), exc)
        emergency_stop(robot)
        raise


class SafetyGuard:
    """Context manager that guarantees motors stop on any exception or exit.

    Usage::

        with SafetyGuard(robot):
            robot_instance.drive_forward(100)
            # motors stopped automatically on exception or exit
    """

    def __init__(self, robot: anki_vector.Robot) -> None:
        self._robot = robot
        self._stop_called = False

    def __enter__(self) -> "SafetyGuard":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        if not self._stop_called:
            emergency_stop(self._robot)
            self._stop_called = True
        # Do not suppress exceptions
        return False

    def stop(self) -> None:
        """Manually trigger stop (idempotent)."""
        if not self._stop_called:
            emergency_stop(self._robot)
            self._stop_called = True


def install_signal_handlers(robot: anki_vector.Robot) -> None:
    """Install SIGINT/SIGTERM handlers that emergency-stop the robot.

    Args:
        robot: Connected anki_vector.Robot instance.

    Note:
        This replaces any existing handlers for SIGINT and SIGTERM.
        Call before entering a control loop.
    """

    def _handler(signum: int, frame: types.FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.warning("Received %s — emergency stopping robot", sig_name)
        emergency_stop(robot)
        raise KeyboardInterrupt(f"Terminated by signal {sig_name}")

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    logger.debug("Signal handlers installed for SIGINT and SIGTERM")