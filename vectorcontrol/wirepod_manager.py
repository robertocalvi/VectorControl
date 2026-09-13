# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

from __future__ import annotations

import logging
import subprocess
import time

import requests

logger = logging.getLogger(__name__)

WIREPOD_APP = "/Applications/WirePod.app"
WIREPOD_URL = "http://192.168.1.3:8080/api-sdk/get_sdk_info"
WIREPOD_CHECK_TIMEOUT = 3


def is_wirepod_running() -> bool:
    try:
        r = requests.get(WIREPOD_URL, timeout=WIREPOD_CHECK_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def launch_wirepod() -> bool:
    try:
        subprocess.Popen(
            ["open", "-a", WIREPOD_APP],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        logger.error("Failed to launch WirePod: %s", exc)
        return False


def ensure_wirepod(max_wait: int = 30) -> bool:
    if is_wirepod_running():
        logger.info("Wire-Pod is already running")
        return True

    logger.warning("Wire-Pod is not running — launching %s", WIREPOD_APP)
    if not launch_wirepod():
        return False

    for i in range(max_wait):
        time.sleep(1)
        if is_wirepod_running():
            logger.info("Wire-Pod started successfully (took %ds)", i + 1)
            return True

    logger.error("Wire-Pod did not start within %ds", max_wait)
    return False
