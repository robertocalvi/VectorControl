# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""VectorConnection - context manager wrapping anki_vector.Robot.

Handles connect/disconnect lifecycle with proper cleanup guarantees.
"""

from __future__ import annotations

import logging
import types
from typing import Optional

import anki_vector

from vectorcontrol.config import RobotConfig, load_config
from vectorcontrol.safety import emergency_stop

logger = logging.getLogger(__name__)


class VectorConnection:
    """Context manager that owns the lifecycle of an anki_vector.Robot connection.

    Usage::

        config = load_config()
        with VectorConnection(config) as conn:
            conn.robot.say_text("Hello")

    On ``__exit__`` (normal or exceptional), motors are stopped and the robot
    is disconnected cleanly.
    """

    def __init__(self, config: Optional[RobotConfig] = None, timeout: int = 15) -> None:
        """
        Args:
            config: RobotConfig to use. Loads from .env/sdk_config.ini if None.
            timeout: Connection timeout in seconds.
        """
        self._config: RobotConfig = config if config is not None else load_config()
        self._timeout = timeout
        self._robot: Optional[anki_vector.Robot] = None
        self._connected = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def robot(self) -> anki_vector.Robot:
        """The underlying anki_vector.Robot instance.

        Raises:
            RuntimeError: If called before connecting.
        """
        if self._robot is None or not self._connected:
            raise RuntimeError(
                "Robot is not connected. Use VectorConnection as a context manager "
                "or call connect() first."
            )
        return self._robot

    def connect(self) -> anki_vector.Robot:
        """Establish connection to the robot.

        Returns:
            The connected anki_vector.Robot instance.

        Raises:
            ConnectionError: If the connection attempt fails.
        """
        if self._connected:
            logger.debug("Already connected to %s", self._config.name)
            return self._robot  # type: ignore[return-value]

        logger.info(
            "Connecting to %s (serial=%s, ip=%s) with timeout=%ds",
            self._config.name,
            self._config.serial,
            self._config.ip,
            self._timeout,
        )

        try:
            self._robot = anki_vector.Robot(serial=self._config.serial)
            self._robot.connect(timeout=self._timeout)
            self._connected = True
            logger.info("Connected to %s", self._config.name)
            return self._robot
        except Exception as exc:
            self._robot = None
            self._connected = False
            raise ConnectionError(
                f"Failed to connect to Vector robot '{self._config.name}' "
                f"(serial={self._config.serial}, ip={self._config.ip}): {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Stop motors and disconnect from the robot.

        Safe to call even if not connected (no-op).
        """
        if not self._connected or self._robot is None:
            return

        logger.info("Disconnecting from %s", self._config.name)

        try:
            emergency_stop(self._robot)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during emergency stop on disconnect: %s", exc)

        try:
            self._robot.disconnect()
            logger.info("Disconnected from %s", self._config.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during disconnect: %s", exc)
        finally:
            self._connected = False
            self._robot = None

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "VectorConnection":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        self.disconnect()
        # Do not suppress exceptions
        return False

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"VectorConnection(name={self._config.name!r}, serial={self._config.serial!r}, status={status})"