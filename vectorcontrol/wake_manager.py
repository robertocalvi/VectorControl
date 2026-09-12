"""wake_manager — Wake sequence logic for Anki Vector.

The wake flow:
  1. Robot is CONNECTED (observation mode, no behavior control).
  2. Caller invokes start_wake() → state → WAKING, background thread spawned.
  3. Thread calls robot.conn.request_control(timeout=N) — blocks up to N seconds.
     • Success → state → AWAKE
     • Failure → state → CONNECTED  (retry allowed)
  4. Caller can release_control() → state → CONNECTED.

All public functions are thread-safe and do NOT touch the asyncio event loop.
The blocking wake_vector() must be called from a dedicated thread, never from
an asyncio coroutine directly (use asyncio.to_thread() if you must await it,
but start_wake() is the preferred non-blocking entry point).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import anki_vector

from vectorcontrol.vector_state import StateContainer, VectorState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core blocking implementation
# ---------------------------------------------------------------------------


MAX_ATTEMPTS = 3
ATTEMPT_TIMEOUT = 10


def wake_vector(
    robot: anki_vector.Robot,
    state: StateContainer,
    timeout: int = 30,
) -> bool:
    """Request behavior control from Vector. **Blocking** — always call from a thread.

    Tries up to MAX_ATTEMPTS times with ATTEMPT_TIMEOUT seconds each.
    If Vector is in deep sleep, request_control blocks until Vector wakes
    (physically touched or hears wake word). The timeout prevents infinite blocking.

    Precondition: state.state must be WAKING when this is called.
    On success:   state → AWAKE, camera initialized.
    On failure:   state → CONNECTED (so the caller can retry).
    """
    if state.state != VectorState.WAKING:
        logger.warning("[WAKE] called but state is %r — aborting", state.state.value)
        return False

    per_attempt = min(ATTEMPT_TIMEOUT, timeout)
    attempts = min(MAX_ATTEMPTS, max(1, timeout // per_attempt))

    for attempt in range(1, attempts + 1):
        logger.info("[WAKE] Attempt %d/%d — request_control(timeout=%ds)…", attempt, attempts, per_attempt)
        try:
            robot.conn.request_control(timeout=per_attempt)
        except Exception as exc:
            logger.warning("[WAKE] Attempt %d failed: %s", attempt, exc)
            if attempt < attempts:
                logger.info("[WAKE] Vector may be in deep sleep — touch his back to wake him")
                continue
            logger.warning("[WAKE] All %d attempts failed — Vector needs physical wake", attempts)
            state.transition(VectorState.CONNECTED, error="Vector is in deep sleep. Touch his back to wake him, then try again.")
            return False

        logger.info("[WAKE] Behavior control granted")
        try:
            robot.camera.init_camera_feed()
            logger.info("[WAKE] Camera feed initialized")
        except Exception as cam_exc:
            logger.warning("[WAKE] Camera init failed (non-fatal): %s", cam_exc)

        state.transition(VectorState.AWAKE)
        logger.info("[WAKE] Vector is AWAKE and READY")
        return True

    state.transition(VectorState.CONNECTED, error="Wake failed")
    return False


# ---------------------------------------------------------------------------
# Non-blocking entry point
# ---------------------------------------------------------------------------


def start_wake(
    robot: anki_vector.Robot,
    state: StateContainer,
    timeout: int = 30,
) -> Optional[threading.Thread]:
    """Transition to WAKING and start wake_vector in a daemon background thread.

    This function returns **immediately** after spawning the thread.
    Poll state.state or call manager.has_control to check progress.

    Args:
        robot:   Connected anki_vector.Robot instance.
        state:   StateContainer — must be in CONNECTED state.
        timeout: Seconds to pass to wake_vector.

    Returns:
        The spawned Thread, or None if the transition was not possible.
    """
    if state.state != VectorState.CONNECTED:
        logger.warning(
            "start_wake: cannot wake from state %r (need 'connected')",
            state.state.value,
        )
        return None

    state.transition(VectorState.WAKING)
    t = threading.Thread(
        target=wake_vector,
        args=(robot, state, timeout),
        name="wake-vector",
        daemon=True,
    )
    t.start()
    logger.debug("Wake thread spawned (id=%d)", t.ident or 0)
    return t


# ---------------------------------------------------------------------------
# Release helper
# ---------------------------------------------------------------------------


def release_control(robot: anki_vector.Robot, state: StateContainer) -> None:
    """Release behavior control back to Vector's autonomous AI.

    Safe to call from any thread.  No-op if state is not AWAKE.

    Args:
        robot: Connected anki_vector.Robot instance.
        state: StateContainer to update.
    """
    if state.state != VectorState.AWAKE:
        logger.debug(
            "release_control: state is %r (not 'awake') — skipping",
            state.state.value,
        )
        return

    try:
        robot.conn.release_control()
        state.transition(VectorState.CONNECTED)
        logger.info("Behavior control released — Vector autonomous AI resumed")
    except Exception as exc:
        logger.warning("release_control failed: %s", exc)
