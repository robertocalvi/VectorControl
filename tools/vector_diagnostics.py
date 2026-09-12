#!/usr/bin/env python3
"""Vector Robot Diagnostics

Comprehensive diagnostics for the Anki Vector + Wire-Pod setup.
Run with: python tools/vector_diagnostics.py

Does NOT print credentials, tokens, or certificate contents.
"""

from __future__ import annotations

import configparser
import http.client
import importlib
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{BOLD}── {title} ──{RESET}")


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_python_version() -> bool:
    section("Python Version")
    major, minor = sys.version_info[:2]
    version_str = f"{major}.{minor}.{sys.version_info.micro}"
    if major == 3 and minor >= 9:
        ok(f"Python {version_str} (OK — 3.9+ required)")
        return True
    else:
        fail(f"Python {version_str} — 3.9+ required")
        return False


def check_sdk_import() -> bool:
    section("SDK Import")
    try:
        import anki_vector  # noqa: F401
        version = getattr(anki_vector, "__version__", "unknown")
        ok(f"anki_vector imported successfully (version={version})")
        return True
    except ImportError as exc:
        fail(f"Cannot import anki_vector: {exc}")
        return False


def check_dotenv_import() -> bool:
    section("python-dotenv Import")
    try:
        import dotenv  # noqa: F401
        ok("python-dotenv imported successfully")
        return True
    except ImportError:
        fail("python-dotenv not installed — run: pip install python-dotenv")
        return False


def check_env_file() -> tuple[bool, dict[str, str]]:
    section(".env File")
    env_path = Path(__file__).parent.parent / ".env"
    env_vars: dict[str, str] = {}

    if not env_path.exists():
        fail(f".env not found at {env_path}")
        return False, env_vars

    ok(f".env found at {env_path}")
    required_keys = ["VECTOR_SERIAL", "VECTOR_IP", "WIREPOD_IP", "WIREPOD_PORT"]
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()

    missing = [k for k in required_keys if k not in env_vars]
    if missing:
        fail(f"Missing keys in .env: {missing}")
        return False, env_vars
    else:
        ok(f"All required keys present: {required_keys}")
        return True, env_vars


def check_sdk_config(serial: str = "00401c2e") -> bool:
    section("SDK Config (sdk_config.ini)")
    config_path = Path.home() / ".anki_vector" / "sdk_config.ini"

    if not config_path.exists():
        fail(f"sdk_config.ini not found at {config_path}")
        return False

    ok(f"sdk_config.ini found at {config_path}")

    parser = configparser.ConfigParser()
    parser.read(config_path)

    if serial not in parser:
        fail(f"Section [{serial}] not found — available: {parser.sections()}")
        return False

    ok(f"Section [{serial}] found")
    section_data = parser[serial]

    required_fields = ["cert", "ip", "name", "guid"]
    missing = [f for f in required_fields if f not in section_data]
    if missing:
        fail(f"Missing fields in [{serial}]: {missing}")
        return False

    ok(f"All required fields present: {required_fields}")
    return True


def check_cert_file(serial: str = "00401c2e") -> bool:
    section("Certificate File")
    config_path = Path.home() / ".anki_vector" / "sdk_config.ini"

    if not config_path.exists():
        fail("sdk_config.ini missing — cannot check cert")
        return False

    parser = configparser.ConfigParser()
    parser.read(config_path)

    if serial not in parser:
        fail(f"Section [{serial}] not found — cannot check cert")
        return False

    cert_str = parser[serial].get("cert", "")
    if not cert_str:
        fail("cert field is empty in sdk_config.ini")
        return False

    cert_path = Path(cert_str).expanduser()
    if not cert_path.exists():
        fail(f"Certificate file not found: {cert_path}")
        return False

    ok(f"Certificate file found: {cert_path.name}")

    try:
        content = cert_path.read_text(encoding="utf-8")
        if "BEGIN CERTIFICATE" in content and "END CERTIFICATE" in content:
            ok("Certificate is valid PEM format")
            return True
        else:
            fail("Certificate file does not contain valid PEM markers")
            return False
    except OSError as exc:
        fail(f"Cannot read certificate: {exc}")
        return False


def check_ping(ip: str) -> bool:
    section(f"Ping Robot ({ip})")
    try:
        result = subprocess.run(
            ["ping", "-c", "2", "-W", "2000", ip],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            ok(f"Ping to {ip} succeeded")
            return True
        else:
            fail(f"Ping to {ip} failed (returncode={result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        fail(f"Ping to {ip} timed out")
        return False
    except Exception as exc:
        fail(f"Ping error: {exc}")
        return False


def check_port(ip: str, port: int, label: str = "") -> bool:
    section(f"Port {port} on {ip} ({label or 'open check'})")
    try:
        with socket.create_connection((ip, port), timeout=5):
            ok(f"Port {port} on {ip} is open")
            return True
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        fail(f"Port {port} on {ip} not reachable: {exc}")
        return False


def check_wirepod(wirepod_ip: str, wirepod_port: int = 8080) -> bool:
    section(f"Wire-Pod Server ({wirepod_ip}:{wirepod_port})")
    url = f"http://{wirepod_ip}:{wirepod_port}"
    try:
        conn = http.client.HTTPConnection(wirepod_ip, wirepod_port, timeout=5)
        conn.request("GET", "/")
        response = conn.getresponse()
        conn.close()
        ok(f"Wire-Pod responded: HTTP {response.status} {response.reason}")
        return True
    except Exception as exc:
        fail(f"Wire-Pod not reachable at {url}: {exc}")
        return False


def check_sdk_connection(serial: str = "00401c2e") -> bool:
    section("SDK Connection Test")
    try:
        import anki_vector  # noqa: F811
    except ImportError:
        fail("anki_vector not importable — skipping connection test")
        return False

    print(f"  Attempting SDK connection (serial={serial}, timeout=10s) …")
    robot = None
    try:
        robot = anki_vector.Robot(serial=serial)
        robot.connect(timeout=10)
        ok(f"SDK connection succeeded — robot name: {getattr(robot, 'name', 'unknown')}")
        return True
    except Exception as exc:
        fail(f"SDK connection failed: {exc}")
        return False
    finally:
        if robot is not None:
            try:
                robot.disconnect()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{BOLD}{'='*50}{RESET}")
    print(f"{BOLD}  Vector Robot Diagnostics{RESET}")
    print(f"{BOLD}{'='*50}{RESET}")

    results: dict[str, bool] = {}

    results["python_version"] = check_python_version()
    results["sdk_import"] = check_sdk_import()
    results["dotenv_import"] = check_dotenv_import()

    env_ok, env_vars = check_env_file()
    results["env_file"] = env_ok

    serial = env_vars.get("VECTOR_SERIAL", "00401c2e")
    robot_ip = env_vars.get("VECTOR_IP", "192.168.1.30")
    wirepod_ip = env_vars.get("WIREPOD_IP", "192.168.1.3")
    wirepod_port = int(env_vars.get("WIREPOD_PORT", "8080"))

    results["sdk_config"] = check_sdk_config(serial)
    results["cert_file"] = check_cert_file(serial)
    results["ping_robot"] = check_ping(robot_ip)
    results["port_443"] = check_port(robot_ip, 443, "robot TLS")
    results["wirepod"] = check_wirepod(wirepod_ip, wirepod_port)
    results["sdk_connection"] = check_sdk_connection(serial)

    # Summary
    section("Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, status in results.items():
        label = name.replace("_", " ").title()
        if status:
            ok(label)
        else:
            fail(label)

    print()
    color = GREEN if passed == total else (YELLOW if passed >= total * 0.7 else RED)
    print(f"  {color}{BOLD}Result: {passed}/{total} checks passed{RESET}")

    if passed < total:
        print(f"\n  {YELLOW}Some checks failed. Review the output above for details.{RESET}")

    print()


if __name__ == "__main__":
    main()
