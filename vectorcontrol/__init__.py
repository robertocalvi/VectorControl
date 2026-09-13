# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""VectorControl - Python library for controlling Anki Vector via Wire-Pod."""

__version__ = "0.1.0"
__author__ = "Roberto"

from vectorcontrol.config import RobotConfig, load_config
from vectorcontrol.connection import VectorConnection
from vectorcontrol.robot import VectorRobot
from vectorcontrol.safety import SafetyGuard, emergency_stop
from vectorcontrol.vector_state import StateContainer, VectorState
from vectorcontrol.wake_manager import release_control, start_wake, wake_vector
from vectorcontrol.vector_manager import VectorManager

__all__ = [
    "RobotConfig",
    "load_config",
    "VectorConnection",
    "VectorRobot",
    "SafetyGuard",
    "emergency_stop",
    "VectorState",
    "StateContainer",
    "wake_vector",
    "start_wake",
    "release_control",
    "VectorManager",
]