# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""wake_manager — Wake sequence for Anki Vector.

Strategy:
  1. Send FakeButtonPress via robot's debug port 8889 to wake Vector
  2. Disconnect the observation-mode connection
  3. Reconnect with behavior_activation_timeout (full behavior control)
  4. Init camera feed
  5. State → AWAKE
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests
import anki_vector

from vectorcontrol.vector_state import StateContainer, VectorState

logger = logging.getLogger(__name__)

ROBOT_DEBUG_PORT = 8889
MAX_ATTEMPTS = 5
WAKE_BURSTS = 3
RECONNECT_TIMEOUT = 15


def _send_fake_button_press(robot_ip: str) -> bool:
    url = f"http://{robot_ip}:{ROBOT_DEBUG_PORT}/consolevarset?key=FakeButtonPressType&value=singlePressDetected"
    try:
        r = requests.get(url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _get_robot_ip(robot: anki_vector.Robot) -> str:
    try:
        return robot.conn.host.split(":")[0]
    except Exception:
        return "192.168.1.30"


def wake_vector(
    robot_holder: list,
    serial: str,
    state: StateContainer,
) -> bool:
    """Full wake sequence. **Blocking** — always call from a thread.

    robot_holder is a single-element list [robot] so we can replace
    the robot instance after reconnecting.

    1. Send wake bursts via debug port
    2. Disconnect observation-mode connection
    3. Reconnect with behavior control
    4. Init camera
    """
    if state.state != VectorState.WAKING:
        logger.warning("[WAKE] called but state is %r — aborting", state.state.value)
        return False

    t0 = time.time()
    old_robot = robot_holder[0]
    robot_ip = _get_robot_ip(old_robot)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("[WAKE] Attempt %d/%d — sending %d wake bursts", attempt, MAX_ATTEMPTS, WAKE_BURSTS)

        for _ in range(WAKE_BURSTS):
            _send_fake_button_press(robot_ip)
            time.sleep(0.3)

        time.sleep(1)

        logger.info("[WAKE] Disconnecting observation-mode connection…")
        try:
            old_robot.disconnect()
        except Exception:
            pass

        logger.info("[WAKE] Reconnecting with behavior control (timeout=%ds)…", RECONNECT_TIMEOUT)
        try:
            new_robot = anki_vector.Robot(serial=serial, behavior_activation_timeout=RECONNECT_TIMEOUT)
            new_robot.connect(timeout=RECONNECT_TIMEOUT)
        except Exception as exc:
            logger.warning("[WAKE] Attempt %d: reconnect failed: %s", attempt, exc)
            try:
                old_robot = anki_vector.Robot(serial=serial, behavior_control_level=None)
                old_robot.connect(timeout=10)
                robot_holder[0] = old_robot
            except Exception:
                pass
            if attempt < MAX_ATTEMPTS:
                continue
            elapsed = int((time.time() - t0) * 1000)
            logger.warning("[WAKE] All %d attempts failed after %dms", MAX_ATTEMPTS, elapsed)
            state.transition(VectorState.CONNECTED, error="Wake failed — Vector may be in deep sleep")
            return False

        logger.info("[WAKE] Connected with behavior control")
        try:
            new_robot.camera.init_camera_feed()
            logger.info("[WAKE] Camera feed initialized")
        except Exception as cam_exc:
            logger.warning("[WAKE] Camera init failed (non-fatal): %s", cam_exc)

        robot_holder[0] = new_robot
        elapsed = int((time.time() - t0) * 1000)
        state.transition(VectorState.AWAKE)
        logger.info("[WAKE] Vector is AWAKE and READY in %dms", elapsed)
        return True

    state.transition(VectorState.CONNECTED, error="Wake failed")
    return False


def start_wake(
    robot_holder: list,
    serial: str,
    state: StateContainer,
) -> Optional[threading.Thread]:
    """Transition to WAKING and start wake_vector in a daemon thread."""
    if state.state != VectorState.CONNECTED:
        logger.warning("start_wake: cannot wake from state %r", state.state.value)
        return None

    state.transition(VectorState.WAKING)
    t = threading.Thread(
        target=wake_vector,
        args=(robot_holder, serial, state),
        name="wake-vector",
        daemon=True,
    )
    t.start()
    return t


def release_control(robot: anki_vector.Robot, state: StateContainer) -> None:
    if state.state != VectorState.AWAKE:
        return
    try:
        try:
            robot.camera.close_camera_feed()
        except Exception:
            pass
        robot.disconnect()
        state.transition(VectorState.DISCONNECTED)
        logger.info("[WAKE] Disconnected — need reconnect for next use")
    except Exception as exc:
        logger.warning("[WAKE] release failed: %s", exc)