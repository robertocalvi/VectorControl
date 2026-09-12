"""VectorState — wake state machine enum and thread-safe state container.

States:
    DISCONNECTED  No connection to robot.
    CONNECTING    SDK connect() in progress.
    CONNECTED     Connected in observation mode; camera works, no behavior control.
    WAKING        request_control() running in background thread (up to 30 s).
    AWAKE         Behavior control granted; all commands available.
    ERROR         Connection failed; inspect StateContainer.error for details.

Transitions:
    DISCONNECTED → CONNECTING → CONNECTED → WAKING → AWAKE
                              ↑ (retry)  ←────────/  (release or failure)
                 → ERROR  (on connect failure)
    Any → DISCONNECTED  (on disconnect)
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum

logger = logging.getLogger(__name__)


class VectorState(str, Enum):
    """All possible wake states.  Values are lowercase strings for easy JSON serialisation."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    WAKING = "waking"
    AWAKE = "awake"
    ERROR = "error"


class StateContainer:
    """Thread-safe holder for the current VectorState.

    Usage::

        state = StateContainer()
        state.transition(VectorState.CONNECTING)
        assert state.state == VectorState.CONNECTING
        assert not state.has_control
    """

    def __init__(self) -> None:
        self._state: VectorState = VectorState.DISCONNECTED
        self._error: str | None = None
        self._updated_at: float = time.monotonic()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> VectorState:
        """Current state (read-only; use transition() to change)."""
        return self._state

    @property
    def error(self) -> str | None:
        """Error message if state is ERROR, else None."""
        return self._error

    @property
    def has_control(self) -> bool:
        """True only when state is AWAKE."""
        return self._state == VectorState.AWAKE

    @property
    def updated_at(self) -> float:
        """Monotonic timestamp of the last state change."""
        return self._updated_at

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def transition(self, new_state: VectorState, error: str | None = None) -> None:
        """Atomically set state (and optional error message).

        Args:
            new_state: Target VectorState.
            error: Human-readable error description (only meaningful for ERROR state).
        """
        with self._lock:
            old = self._state
            self._state = new_state
            self._error = error
            self._updated_at = time.monotonic()

        if old != new_state:
            suffix = f" ({error})" if error else ""
            logger.debug("VectorState: %s → %s%s", old.value, new_state.value, suffix)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot."""
        return {
            "state": self._state.value,
            "has_control": self.has_control,
            "error": self._error,
        }

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"StateContainer(state={self._state.value!r}, error={self._error!r})"
