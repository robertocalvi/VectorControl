# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Wire-Pod lifecycle manager.

NETWORK CONFIGURATION:
    Wire-Pod IP and port are read from .env via vectorcontrol.config:
        WIREPOD_IP=192.168.1.3   (your Mac's IP on the local network)
        WIREPOD_PORT=8080

    When moving to a different network, update WIREPOD_IP in .env
    to match your Mac's new local IP. Wire-Pod port rarely changes.

    If WIREPOD_IP is empty, Wire-Pod check is skipped (assumes running).
"""

from __future__ import annotations

import logging
import subprocess
import time

import requests

logger = logging.getLogger(__name__)

WIREPOD_APP = "/Applications/WirePod.app"
WIREPOD_CHECK_TIMEOUT = 3

_wirepod_ip: str = ""
_wirepod_port: int = 8080


def configure(ip: str, port: int = 8080) -> None:
    global _wirepod_ip, _wirepod_port
    _wirepod_ip = ip
    _wirepod_port = port


def _get_url() -> str:
    return f"http://{_wirepod_ip}:{_wirepod_port}/api-sdk/get_sdk_info"


def is_wirepod_running() -> bool:
    if not _wirepod_ip:
        return True
    try:
        r = requests.get(_get_url(), timeout=WIREPOD_CHECK_TIMEOUT)
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
    if not _wirepod_ip:
        logger.info("WIREPOD_IP not set — skipping Wire-Pod check")
        return True

    if is_wirepod_running():
        logger.info("Wire-Pod is already running at %s:%d", _wirepod_ip, _wirepod_port)
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
