"""wake_manager — Wake sequence logic for Anki Vector.

Wake flow:
  1. CONNECTED → WAKING
  2. Send FakeButtonPress via robot's debug port 8889 (simulates physical touch)
  3. Wait briefly for Vector to react
  4. request_control(timeout) — should succeed quickly now
  5. Init camera feed
  6. WAKING → AWAKE

Three wake methods available (tried in order):
  - Direct consolevars: HTTP to robot:8889 (fastest, 31ms)
  - Wire-Pod trigger_wake_word: HTTP to Wire-Pod (proxy, 952ms)
  - Blind request_control: just try control without wake stimulus (works if already awake)
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
WIREPOD_PORT = 8080
MAX_ATTEMPTS = 5
POST_WAKE_DELAY = 1.0
CONTROL_TIMEOUT = 3
WAKE_BURSTS = 3


def _send_fake_button_press(robot_ip: str) -> bool:
    url = f"http://{robot_ip}:{ROBOT_DEBUG_PORT}/consolevarset?key=FakeButtonPressType&value=singlePressDetected"
    logger.info("[WAKE] Sending FakeButtonPress to %s:%d", robot_ip, ROBOT_DEBUG_PORT)
    try:
        r = requests.get(url, timeout=5)
        ok = r.status_code == 200
        logger.info("[WAKE] FakeButtonPress: %s (status=%d)", "OK" if ok else "FAILED", r.status_code)
        return ok
    except Exception as exc:
        logger.warning("[WAKE] FakeButtonPress failed: %s", exc)
        return False


def _send_wirepod_trigger(wirepod_ip: str, serial: str) -> bool:
    url = f"http://{wirepod_ip}:{WIREPOD_PORT}/api-sdk/trigger_wake_word?serial={serial}"
    logger.info("[WAKE] Sending trigger_wake_word via Wire-Pod")
    try:
        r = requests.get(url, timeout=10)
        ok = r.status_code == 200 and "success" in r.text.lower()
        logger.info("[WAKE] Wire-Pod trigger: %s (response=%r)", "OK" if ok else "FAILED", r.text.strip())
        return ok
    except Exception as exc:
        logger.warning("[WAKE] Wire-Pod trigger failed: %s", exc)
        return False


def _get_robot_ip(robot: anki_vector.Robot) -> str:
    try:
        return robot.conn.host.split(":")[0]
    except Exception:
        return "192.168.1.30"


def _get_wirepod_ip() -> str:
    return "192.168.1.3"


def wake_vector(
    robot: anki_vector.Robot,
    state: StateContainer,
    timeout: int = 30,
) -> bool:
    """Full wake sequence. **Blocking** — always call from a thread.

    1. Send wake stimulus (FakeButtonPress via debug port)
    2. Wait for Vector to react
    3. request_control with timeout
    4. Init camera

    On success: state → AWAKE.
    On failure: state → CONNECTED (retryable).
    """
    if state.state != VectorState.WAKING:
        logger.warning("[WAKE] called but state is %r — aborting", state.state.value)
        return False

    t0 = time.time()
    robot_ip = _get_robot_ip(robot)
    serial = robot.serial if hasattr(robot, "serial") else "00401c2e"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("[WAKE] Attempt %d/%d", attempt, MAX_ATTEMPTS)

        for burst in range(WAKE_BURSTS):
            _send_fake_button_press(robot_ip)
            time.sleep(0.3)
        logger.info("[WAKE] Sent %d wake bursts — waiting %.1fs", WAKE_BURSTS, POST_WAKE_DELAY)
        time.sleep(POST_WAKE_DELAY)

        logger.info("[WAKE] Requesting behavior control (timeout=%ds)…", CONTROL_TIMEOUT)
        try:
            robot.conn.request_control(timeout=CONTROL_TIMEOUT)
            # Patch SDK internals: when connected with behavior_control_level=None,
            # the SDK refuses motor commands even after request_control() succeeds.
            # Setting _behavior_control_level makes requires_behavior_control return True,
            # which allows motor commands to proceed.
            from anki_vector.connection import ControlPriorityLevel
            if robot.conn._behavior_control_level is None:
                robot.conn._behavior_control_level = ControlPriorityLevel.DEFAULT_PRIORITY
                logger.info("[WAKE] Patched _behavior_control_level for motor commands")
        except Exception as exc:
            logger.warning("[WAKE] Attempt %d: request_control failed: %s", attempt, exc)
            if attempt < MAX_ATTEMPTS:
                continue
            elapsed = int((time.time() - t0) * 1000)
            logger.warning("[WAKE] All %d attempts failed after %dms", MAX_ATTEMPTS, elapsed)
            state.transition(VectorState.CONNECTED, error="Wake failed — could not get behavior control")
            return False

        logger.info("[WAKE] Behavior control granted")
        try:
            robot.camera.init_camera_feed()
            logger.info("[WAKE] Camera feed initialized")
        except Exception as cam_exc:
            logger.warning("[WAKE] Camera init failed (non-fatal): %s", cam_exc)

        elapsed = int((time.time() - t0) * 1000)
        state.transition(VectorState.AWAKE)
        logger.info("[WAKE] Vector is AWAKE and READY in %dms", elapsed)
        return True

    state.transition(VectorState.CONNECTED, error="Wake failed")
    return False


def start_wake(
    robot: anki_vector.Robot,
    state: StateContainer,
    timeout: int = 30,
) -> Optional[threading.Thread]:
    """Transition to WAKING and start wake_vector in a daemon thread. Returns immediately."""
    if state.state != VectorState.CONNECTED:
        logger.warning("start_wake: cannot wake from state %r", state.state.value)
        return None

    state.transition(VectorState.WAKING)
    t = threading.Thread(
        target=wake_vector,
        args=(robot, state, timeout),
        name="wake-vector",
        daemon=True,
    )
    t.start()
    return t


def release_control(robot: anki_vector.Robot, state: StateContainer) -> None:
    """Release behavior control. No-op if not AWAKE."""
    if state.state != VectorState.AWAKE:
        return
    try:
        robot.conn.release_control()
        try:
            robot.camera.close_camera_feed()
        except Exception:
            pass
        state.transition(VectorState.CONNECTED)
        logger.info("[WAKE] Control released — Vector autonomous")
    except Exception as exc:
        logger.warning("[WAKE] release_control failed: %s", exc)
