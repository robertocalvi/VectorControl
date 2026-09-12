"""VectorManager — high-level manager that owns the robot connection.

Owns:
  • The anki_vector.Robot instance (observation mode by default).
  • The StateContainer (single source of truth for wake state).

Delegates:
  • Wake sequence → wake_manager.start_wake() / wake_manager.release_control()

Thread safety:
  • connect() and disconnect() acquire _conn_lock so they can't race.
  • wake() and release() are idempotent and guarded by state checks.
  • All blocking SDK calls belong in threads; this class does NOT touch asyncio.

Usage (from a FastAPI lifespan)::

    manager = VectorManager(serial="00401c2e")

    # startup
    await asyncio.to_thread(manager.connect)

    # handle request — non-blocking
    manager.wake()          # returns immediately; background thread wakes Vector

    # handle request — blocking, run in thread
    manager.ensure_control()
    await asyncio.to_thread(robot.motors.set_wheel_motors, 80, 80)

    # shutdown
    await asyncio.to_thread(manager.disconnect)
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import anki_vector

from vectorcontrol.vector_state import StateContainer, VectorState
from vectorcontrol.wake_manager import (
    release_control as _release_control,
    start_wake,
)

logger = logging.getLogger(__name__)

_DEFAULT_SERIAL = "00401c2e"


class VectorManager:
    """Owns the robot connection lifecycle and delegates wake/sleep to wake_manager.

    Attributes:
        serial: Robot serial number.
        state:  Live StateContainer — poll ``state.state`` or ``state.has_control``.
    """

    def __init__(self, serial: str = _DEFAULT_SERIAL) -> None:
        self.serial = serial
        self.state = StateContainer()
        self._robot: Optional[anki_vector.Robot] = None
        self._conn_lock = threading.Lock()
        self._wake_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def robot(self) -> Optional[anki_vector.Robot]:
        """The connected anki_vector.Robot, or None if not connected."""
        return self._robot

    @property
    def is_connected(self) -> bool:
        """True while a robot instance exists (observation or awake)."""
        return self._robot is not None

    @property
    def has_control(self) -> bool:
        """True only when behavior control is held (state == AWAKE)."""
        return self.state.has_control

    # ------------------------------------------------------------------
    # Connection lifecycle  (blocking — use asyncio.to_thread)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to Vector in observation mode.

        **Blocking** — wraps robot.connect() which may take up to 15 s.
        Call via ``await asyncio.to_thread(manager.connect)``.

        On success: state → CONNECTED.
        On failure: state → ERROR (error message in state.error).
        """
        with self._conn_lock:
            if self.state.state not in (VectorState.DISCONNECTED, VectorState.ERROR):
                logger.debug("connect(): already in state %r — skipping", self.state.state.value)
                return
            self.state.transition(VectorState.CONNECTING)

        try:
            logger.info(
                "Connecting to Vector (serial=%s) in observation mode (timeout=15s)…",
                self.serial,
            )
            robot = anki_vector.Robot(serial=self.serial, behavior_control_level=None)
            robot.connect(timeout=15)
            robot.camera.init_camera_feed()
            self._robot = robot
            self.state.transition(VectorState.CONNECTED)
            logger.info("Connected — firmware %s", self._safe_firmware())
        except Exception as exc:
            self._robot = None
            self.state.transition(VectorState.ERROR, str(exc))
            logger.error("Connection failed: %s", exc)

    def disconnect(self) -> None:
        """Stop motors, close camera, and disconnect.

        **Blocking** — call via ``await asyncio.to_thread(manager.disconnect)``.
        Safe to call even if not connected.
        """
        with self._conn_lock:
            robot = self._robot
            self._robot = None
            self.state.transition(VectorState.DISCONNECTED)

        if robot is None:
            return

        for _attempt, fn in enumerate(
            [
                lambda: robot.motors.stop_all_motors(),
                lambda: robot.camera.close_camera_feed(),
                lambda: robot.disconnect(),
            ]
        ):
            try:
                fn()
            except Exception as exc:
                logger.debug("disconnect cleanup error (non-fatal): %s", exc)

        logger.info("Disconnected from Vector")

    # ------------------------------------------------------------------
    # Wake lifecycle  (non-blocking — returns immediately)
    # ------------------------------------------------------------------

    def wake(self, timeout: int = 30) -> bool:
        """Start the wake sequence in a background thread.

        Returns **immediately**.  Poll ``manager.has_control`` or
        ``manager.state.state`` to check progress.

        Args:
            timeout: Seconds to pass to request_control().

        Returns:
            True  — wake thread spawned (or already AWAKE).
            False — cannot wake (not connected, already waking, wrong state).
        """
        if self._robot is None:
            logger.warning("wake(): not connected — cannot wake")
            return False

        if self.state.state == VectorState.AWAKE:
            logger.debug("wake(): already AWAKE")
            return True

        if self.state.state == VectorState.WAKING:
            logger.debug("wake(): already waking — ignoring duplicate request")
            return False

        if self.state.state != VectorState.CONNECTED:
            logger.warning(
                "wake(): invalid state %r — need 'connected'",
                self.state.state.value,
            )
            return False

        self._wake_thread = start_wake(self._robot, self.state, timeout=timeout)
        return self._wake_thread is not None

    def release(self) -> None:
        """Release behavior control back to Vector.

        **Blocking** — wraps robot.conn.release_control().
        Call via ``await asyncio.to_thread(manager.release)``.
        No-op if not AWAKE.
        """
        if self._robot is None:
            return
        _release_control(self._robot, self.state)

    # ------------------------------------------------------------------
    # Guard
    # ------------------------------------------------------------------

    def ensure_control(self) -> None:
        """Raise RuntimeError if behavior control is not held.

        Use before any command that requires AWAKE state::

            manager.ensure_control()
            robot.motors.set_wheel_motors(80, 80)
        """
        if not self.has_control:
            raise RuntimeError(
                f"No behavior control — current state: {self.state.state.value!r}. "
                "Wake Vector first (POST /api/wake or click WAKE UP VECTOR)."
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_firmware(self) -> str:
        """Return firmware version string without raising."""
        try:
            if self._robot is not None:
                return self._robot.get_version_state().os_version
        except Exception:
            pass
        return "unknown"

    def __repr__(self) -> str:
        return (
            f"VectorManager(serial={self.serial!r}, "
            f"state={self.state.state.value!r}, "
            f"connected={self.is_connected})"
        )
