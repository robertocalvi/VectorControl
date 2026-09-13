# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""VectorManager — high-level manager that owns the robot connection.

Strategy:
  1. connect() → observation mode (instant, no behavior control needed)
  2. wake() → sends FakeButtonPress, disconnects, reconnects with behavior control
  3. After wake: robot has full control, camera works, motors work
  4. release() → disconnects, reconnects in observation mode
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import anki_vector

from vectorcontrol.vector_state import StateContainer, VectorState
from vectorcontrol import wake_manager

logger = logging.getLogger(__name__)

_DEFAULT_SERIAL = "00401c2e"


class VectorManager:

    def __init__(self, serial: str = _DEFAULT_SERIAL) -> None:
        self.serial = serial
        self.state = StateContainer()
        self._robot: Optional[anki_vector.Robot] = None
        self._conn_lock = threading.Lock()
        self._wake_thread: Optional[threading.Thread] = None

    @property
    def robot(self) -> Optional[anki_vector.Robot]:
        return self._robot

    @property
    def is_connected(self) -> bool:
        return self._robot is not None

    @property
    def has_control(self) -> bool:
        return self.state.has_control

    def connect(self, retries: int = 3, delay: float = 5.0) -> None:
        with self._conn_lock:
            if self.state.state not in (VectorState.DISCONNECTED, VectorState.ERROR):
                return
            self.state.transition(VectorState.CONNECTING)

        import time
        for attempt in range(1, retries + 1):
            try:
                logger.info("Connecting to Vector (serial=%s) attempt %d/%d…", self.serial, attempt, retries)
                robot = anki_vector.Robot(serial=self.serial, behavior_control_level=None)
                robot.connect(timeout=15)
                self._robot = robot
                self.state.transition(VectorState.CONNECTED)
                logger.info("Connected — firmware %s", self._safe_firmware())
                return
            except Exception as exc:
                logger.warning("Connection attempt %d failed: %s", attempt, exc)
                try:
                    robot.disconnect()
                except Exception:
                    pass
                if attempt < retries:
                    logger.info("Retrying in %.0fs…", delay)
                    time.sleep(delay)

        self._robot = None
        self.state.transition(VectorState.ERROR, "All connection attempts failed")
        logger.error("Connection failed after %d attempts", retries)

    def disconnect(self) -> None:
        with self._conn_lock:
            robot = self._robot
            self._robot = None
            self.state.transition(VectorState.DISCONNECTED)

        if robot is None:
            return
        try:
            robot.disconnect()
        except Exception:
            pass
        logger.info("Disconnected from Vector")

    def wake(self, timeout: int = 30) -> bool:
        if self._robot is None:
            logger.warning("wake(): not connected")
            return False
        if self.state.state == VectorState.AWAKE:
            return True
        if self.state.state == VectorState.WAKING:
            return False
        if self.state.state != VectorState.CONNECTED:
            logger.warning("wake(): invalid state %r", self.state.state.value)
            return False

        # wake_manager needs a mutable reference to replace the robot instance
        robot_holder = [self._robot]
        self._wake_thread = wake_manager.start_wake(robot_holder, self.serial, self.state)

        # Monitor thread to update self._robot when wake completes
        def _on_wake_done():
            if self._wake_thread:
                self._wake_thread.join()
            self._robot = robot_holder[0]

        threading.Thread(target=_on_wake_done, daemon=True).start()
        return self._wake_thread is not None

    def release(self) -> None:
        if self._robot is None:
            return
        wake_manager.release_control(self._robot, self.state)
        self._robot = None
        # Reconnect in observation mode
        try:
            robot = anki_vector.Robot(serial=self.serial, behavior_control_level=None)
            robot.connect(timeout=10)
            self._robot = robot
            self.state.transition(VectorState.CONNECTED)
            logger.info("Reconnected in observation mode after release")
        except Exception as exc:
            logger.warning("Reconnect after release failed: %s", exc)
            self.state.transition(VectorState.DISCONNECTED)

    def ensure_control(self) -> None:
        if not self.has_control:
            raise RuntimeError(
                f"No behavior control (state={self.state.state.value}). "
                "Press WAKE UP VECTOR first."
            )

    def _safe_firmware(self) -> str:
        try:
            if self._robot is not None:
                return self._robot.get_version_state().os_version
        except Exception:
            pass
        return "unknown"