"""Configuration loader for VectorControl.

Reads .env and ~/.anki_vector/sdk_config.ini to build a RobotConfig.
Never logs credentials, tokens, or certificate contents.
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RobotConfig:
    serial: str
    ip: str
    name: str
    cert_path: Path
    guid: str
    wirepod_ip: str
    wirepod_port: int


def load_config(env_file: Path | None = None) -> RobotConfig:
    """Load robot configuration from .env and sdk_config.ini.

    Args:
        env_file: Path to .env file. Defaults to VectorControl project root.

    Returns:
        RobotConfig with all required fields populated.

    Raises:
        FileNotFoundError: If sdk_config.ini or cert file is missing.
        KeyError: If required keys are absent from config.
        ValueError: If configuration is invalid.
    """
    # Resolve .env location (caller's parent or explicit path)
    if env_file is None:
        env_file = Path(__file__).parent.parent / ".env"

    if env_file.exists():
        load_dotenv(env_file)
        logger.debug("Loaded .env from %s", env_file)
    else:
        logger.warning(".env not found at %s; relying on environment variables", env_file)

    # Read sdk_config.ini
    sdk_config_path = Path.home() / ".anki_vector" / "sdk_config.ini"
    if not sdk_config_path.exists():
        raise FileNotFoundError(
            f"SDK config not found: {sdk_config_path}\n"
            "Run the Vector authentication setup first."
        )

    parser = configparser.ConfigParser()
    parser.read(sdk_config_path)

    # Determine serial: prefer .env, fallback to first section in ini
    serial = os.environ.get("VECTOR_SERIAL", "").strip()
    if not serial:
        sections = parser.sections()
        if not sections:
            raise ValueError("sdk_config.ini has no robot sections")
        serial = sections[0]
        logger.debug("VECTOR_SERIAL not set; using first section: %s", serial)

    if serial not in parser:
        raise KeyError(
            f"Serial [{serial}] not found in sdk_config.ini. "
            f"Available: {parser.sections()}"
        )

    section = parser[serial]

    # Read fields from ini (they override env where ini is authoritative)
    ip = os.environ.get("VECTOR_IP", "").strip() or section.get("ip", "")
    name = section.get("name", f"Vector-{serial}")
    guid = section.get("guid", "")
    cert_raw = section.get("cert", "")
    cert_path = Path(cert_raw).expanduser() if cert_raw else Path.home() / ".anki_vector" / f"{name}-{serial}.cert"

    if not ip:
        raise ValueError(f"Robot IP not found in .env (VECTOR_IP) or sdk_config.ini [{serial}]")

    if not cert_path.exists():
        raise FileNotFoundError(
            f"Certificate file not found: {cert_path}\n"
            "Re-authenticate the robot with Wire-Pod."
        )

    # Validate PEM header without printing contents
    try:
        cert_text = cert_path.read_text(encoding="utf-8")
        if "BEGIN CERTIFICATE" not in cert_text:
            raise ValueError(f"Certificate file does not appear to be valid PEM: {cert_path}")
    except OSError as exc:
        raise FileNotFoundError(f"Cannot read certificate: {cert_path}") from exc

    wirepod_ip = os.environ.get("WIREPOD_IP", "").strip()
    wirepod_port_str = os.environ.get("WIREPOD_PORT", "8080").strip()

    try:
        wirepod_port = int(wirepod_port_str)
    except ValueError:
        raise ValueError(f"WIREPOD_PORT must be an integer, got: {wirepod_port_str!r}")

    config = RobotConfig(
        serial=serial,
        ip=ip,
        name=name,
        cert_path=cert_path,
        guid=guid,
        wirepod_ip=wirepod_ip,
        wirepod_port=wirepod_port,
    )

    logger.info(
        "Loaded config: robot=%s serial=%s ip=%s wirepod=%s:%d",
        config.name,
        config.serial,
        config.ip,
        config.wirepod_ip,
        config.wirepod_port,
    )
    return config
