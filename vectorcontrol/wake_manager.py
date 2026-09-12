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


def wake_vector(
    robot: anki_vector.Robot,
    state: StateContainer,
    timeout: int = 30,
) -> bool:
    """Request behavior control from Vector.  **Blocking** — always call from a thread.

    Precondition: state.state must be WAKING when this is called.
    On success:   state → AWAKE.
    On failure:   state → CONNECTED  (so the caller can retry).

    Args:
        robot:   Connected anki_vector.Robot instance (observation mode).
        state:   StateContainer to update during the wake sequence.
        timeout: Maximum seconds to wait for behavior control.

    Returns:
        True if control was granted, False otherwise.
    """
    if state.state != VectorState.WAKING:
        logger.warning(
            "wake_vector called but state is %r (expected 'waking') — aborting",
            state.state.value,
        )
        return False

    try:
        logger.info("Requesting behavior control (timeout=%ds)…", timeout)
        robot.conn.request_control(timeout=timeout)
        state.transition(VectorState.AWAKE)
        logger.info("Behavior control granted — Vector is AWAKE")
        return True
    except Exception as exc:
        logger.warning("wake_vector failed: %s", exc)
        # Return to CONNECTED so the caller may retry
        state.transition(VectorState.CONNECTED)
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
