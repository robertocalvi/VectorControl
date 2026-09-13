# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import anki_vector

from vectorcontrol.vector_state import StateContainer, VectorState
from vectorcontrol import wake_manager

logger = logging.getLogger(__name__)

_DEFAULT_SERIAL = "00401c2e"
ROBOT_DEBUG_PORT = 8889

HEARTBEAT_INTERVAL = 10
RECONNECT_INTERVAL = 15
CONNECT_TIMEOUT = 15
RECOVERY_WAIT = 30


class VectorManager:

    def __init__(self, serial: str = _DEFAULT_SERIAL) -> None:
        self.serial = serial
        self.state = StateContainer()
        self._robot: Optional[anki_vector.Robot] = None
        self._conn_lock = threading.Lock()
        self._wake_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._reconnect_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

    @property
    def robot(self) -> Optional[anki_vector.Robot]:
        return self._robot

    @property
    def is_connected(self) -> bool:
        return self._robot is not None

    @property
    def has_control(self) -> bool:
        return self.state.has_control

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._shutdown.clear()
        self._start_reconnect_loop()

    def stop(self) -> None:
        self._shutdown.set()
        self.disconnect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _try_connect(self) -> bool:
        if self._shutdown.is_set():
            return False
        with self._conn_lock:
            if self._robot is not None:
                return True
            if self.state.state not in (VectorState.DISCONNECTED, VectorState.ERROR):
                if self.state.state == VectorState.CONNECTING:
                    return False
                return self._robot is not None
            self.state.transition(VectorState.CONNECTING)

        result = [None, None]

        def _do_connect():
            try:
                robot = anki_vector.Robot(serial=self.serial, behavior_control_level=None)
                robot.connect(timeout=CONNECT_TIMEOUT)
                result[0] = robot
            except Exception as exc:
                result[1] = exc
                try:
                    robot.disconnect()
                except Exception:
                    pass

        logger.info("Connecting to Vector (serial=%s)…", self.serial)
        t = threading.Thread(target=_do_connect, daemon=True)
        t.start()
        t.join(timeout=CONNECT_TIMEOUT + 5)

        if t.is_alive():
            logger.warning("Connection timed out (SDK hung)")
            self._robot = None
            self.state.transition(VectorState.DISCONNECTED)
            return False

        if result[0] is not None:
            self._robot = result[0]
            self.state.transition(VectorState.CONNECTED)
            logger.info("Connected — firmware %s", self._safe_firmware())
            self._start_heartbeat()
            return True

        logger.warning("Connection failed: %s", result[1])
        self._robot = None
        self.state.transition(VectorState.DISCONNECTED)
        return False

    def disconnect(self) -> None:
        self._stop_heartbeat()
        with self._conn_lock:
            robot = self._robot
            self._robot = None
            if self.state.state != VectorState.DISCONNECTED:
                self.state.transition(VectorState.DISCONNECTED)

        if robot is None:
            return
        try:
            robot.disconnect()
        except Exception:
            pass
        logger.info("Disconnected from Vector")

    def _force_reconnect(self) -> None:
        logger.info("Force reconnect — dropping gRPC to let Vector recover")
        self._stop_heartbeat()
        robot = self._robot
        self._robot = None
        self.state.transition(VectorState.DISCONNECTED)
        if robot is not None:
            try:
                robot.disconnect()
            except Exception:
                pass

        self._send_wake_bursts()
        logger.info("Waiting 30s for Vector to self-restart…")
        if self._shutdown.wait(timeout=30):
            return

    def _send_wake_bursts(self) -> None:
        import requests as _req
        for burst in range(3):
            for _ in range(3):
                try:
                    _req.get(
                        f"http://192.168.1.30:{ROBOT_DEBUG_PORT}/consolevarset"
                        "?key=FakeButtonPressType&value=singlePressDetected",
                        timeout=3,
                    )
                except Exception:
                    pass
                time.sleep(0.3)
            time.sleep(1)

    # ------------------------------------------------------------------
    # Background reconnect loop — retries forever until connected
    # ------------------------------------------------------------------

    def _start_reconnect_loop(self) -> None:
        if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
            return
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            name="reconnect-loop",
            daemon=True,
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        while not self._shutdown.is_set():
            if self._robot is None and self.state.state in (VectorState.DISCONNECTED, VectorState.ERROR):
                logger.info("Reconnect loop: attempting connection…")
                self._try_connect()

            if self._shutdown.wait(timeout=RECONNECT_INTERVAL):
                break

    # ------------------------------------------------------------------
    # Heartbeat — detects dead connections
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        current_thread = self._heartbeat_thread
        consecutive_failures = 0

        while not self._shutdown.is_set() and self._heartbeat_thread is current_thread:
            if self._shutdown.wait(timeout=HEARTBEAT_INTERVAL):
                break
            if self._heartbeat_thread is not current_thread:
                break

            robot = self._robot
            if robot is None:
                break

            try:
                robot.get_battery_state()
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                logger.warning("Heartbeat failed (%d consecutive)", consecutive_failures)
                if consecutive_failures >= 2:
                    logger.error("Heartbeat: connection dead — triggering reconnect")
                    self._force_reconnect()
                    break

    # ------------------------------------------------------------------
    # Wake
    # ------------------------------------------------------------------

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

        self._stop_heartbeat()

        robot_holder = [self._robot]
        self._wake_thread = wake_manager.start_wake(robot_holder, self.serial, self.state)

        def _on_wake_done():
            if self._wake_thread:
                self._wake_thread.join()
            self._robot = robot_holder[0]
            if self.state.state == VectorState.AWAKE:
                self._start_heartbeat()

        threading.Thread(target=_on_wake_done, daemon=True).start()
        return self._wake_thread is not None

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    def release(self) -> None:
        if self._robot is None:
            return
        self._stop_heartbeat()
        wake_manager.release_control(self._robot, self.state)
        self._robot = None
        time.sleep(1)
        self._try_connect()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
