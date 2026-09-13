#!/usr/bin/env python3
# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Test wake methods via Wire-Pod API and Vector's internal debug port.

Tests three levels:
  1. Wire-Pod /api-sdk/trigger_wake_word (simulates button press via consolevars)
  2. Direct robot consolevars on port 8889
  3. Wire-Pod /api-sdk/cloud_intent (sends AppIntent via Wire-Pod's gRPC)

After each test, attempts request_control(timeout=2) to verify if Vector woke up.

Usage:
    .venv/bin/python tools/test_wirepod_wake.py --list
    .venv/bin/python tools/test_wirepod_wake.py --method trigger_wake_word
    .venv/bin/python tools/test_wirepod_wake.py --method consolevars_button
    .venv/bin/python tools/test_wirepod_wake.py --method cloud_intent_wake
    .venv/bin/python tools/test_wirepod_wake.py --method cloud_intent_hello
    .venv/bin/python tools/test_wirepod_wake.py --all
"""

import argparse
import sys
import time

import requests
import anki_vector

SERIAL = "00401c2e"
ROBOT_IP = "192.168.1.30"
WIREPOD_IP = "192.168.1.3"
WIREPOD_PORT = 8080
ROBOT_DEBUG_PORT = 8889


def wirepod_url(path: str) -> str:
    return f"http://{WIREPOD_IP}:{WIREPOD_PORT}{path}"


def robot_debug_url(path: str) -> str:
    return f"http://{ROBOT_IP}:{ROBOT_DEBUG_PORT}{path}"


def check_reachable() -> dict:
    results = {}

    print("[CHECK] Robot gRPC (192.168.1.30:443)...")
    try:
        robot = anki_vector.Robot(serial=SERIAL, behavior_control_level=None)
        robot.connect(timeout=10)
        bat = robot.get_battery_state()
        results["grpc"] = True
        results["battery_volts"] = round(bat.battery_volts, 2)
        results["on_charger"] = bat.is_on_charger_platform
        results["charging"] = bat.is_charging
        results["robot"] = robot
        print(f"[CHECK] gRPC: OK — {bat.battery_volts:.2f}V, charger={bat.is_on_charger_platform}")
    except Exception as e:
        results["grpc"] = False
        results["robot"] = None
        print(f"[CHECK] gRPC: FAILED — {e}")

    print(f"[CHECK] Wire-Pod ({WIREPOD_IP}:{WIREPOD_PORT})...")
    try:
        r = requests.get(wirepod_url("/api-sdk/get_sdk_info"), timeout=5)
        results["wirepod"] = r.status_code == 200
        print(f"[CHECK] Wire-Pod: {'OK' if results['wirepod'] else 'FAILED'} — {r.text[:100]}")
    except Exception as e:
        results["wirepod"] = False
        print(f"[CHECK] Wire-Pod: FAILED — {e}")

    print(f"[CHECK] Robot debug port ({ROBOT_IP}:{ROBOT_DEBUG_PORT})...")
    try:
        r = requests.get(robot_debug_url("/"), timeout=3)
        results["debug_port"] = r.status_code == 200
        print(f"[CHECK] Debug port: OK — {len(r.text)} bytes")
    except Exception as e:
        results["debug_port"] = False
        print(f"[CHECK] Debug port: FAILED — {e}")

    return results


def verify_wake(robot) -> bool:
    """Try request_control with short timeout. Returns True if control granted."""
    print("[VERIFY] Attempting request_control(timeout=3)...")
    t0 = time.time()
    try:
        robot.conn.request_control(timeout=3)
        dt = (time.time() - t0) * 1000
        print(f"[VERIFY] CONTROL GRANTED in {dt:.0f}ms — WOKE_VECTOR = TRUE")
        robot.conn.release_control()
        return True
    except Exception as exc:
        dt = (time.time() - t0) * 1000
        print(f"[VERIFY] CONTROL FAILED in {dt:.0f}ms — WOKE_VECTOR = FALSE ({exc})")
        return False


def test_trigger_wake_word(robot) -> bool:
    """Wire-Pod /api-sdk/trigger_wake_word — simulates button press via consolevars."""
    print("[TEST] trigger_wake_word: calling Wire-Pod API...")
    t0 = time.time()
    try:
        r = requests.get(
            wirepod_url(f"/api-sdk/trigger_wake_word?serial={SERIAL}"),
            timeout=10,
        )
        dt = (time.time() - t0) * 1000
        print(f"[TEST] trigger_wake_word: response={r.text.strip()!r} status={r.status_code} ({dt:.0f}ms)")
        time.sleep(3)
        return True
    except Exception as e:
        dt = (time.time() - t0) * 1000
        print(f"[TEST] trigger_wake_word: FAILED — {e} ({dt:.0f}ms)")
        return False


def test_consolevars_button(robot) -> bool:
    """Direct HTTP to robot:8889 — FakeButtonPressType=singlePressDetected."""
    url = robot_debug_url("/consolevarset?key=FakeButtonPressType&value=singlePressDetected")
    print(f"[TEST] consolevars_button: GET {url}")
    t0 = time.time()
    try:
        r = requests.get(url, timeout=10)
        dt = (time.time() - t0) * 1000
        print(f"[TEST] consolevars_button: response={r.text.strip()[:200]!r} status={r.status_code} ({dt:.0f}ms)")
        time.sleep(3)
        return True
    except Exception as e:
        dt = (time.time() - t0) * 1000
        print(f"[TEST] consolevars_button: FAILED — {e} ({dt:.0f}ms)")
        return False


def test_cloud_intent(robot, intent: str) -> bool:
    """Wire-Pod /api-sdk/cloud_intent — sends AppIntent via Wire-Pod's gRPC connection."""
    print(f"[TEST] cloud_intent({intent!r}): calling Wire-Pod API...")
    t0 = time.time()
    try:
        r = requests.get(
            wirepod_url(f"/api-sdk/cloud_intent?serial={SERIAL}&intent={intent}"),
            timeout=10,
        )
        dt = (time.time() - t0) * 1000
        print(f"[TEST] cloud_intent: response={r.text.strip()!r} status={r.status_code} ({dt:.0f}ms)")
        time.sleep(3)
        return True
    except Exception as e:
        dt = (time.time() - t0) * 1000
        print(f"[TEST] cloud_intent: FAILED — {e} ({dt:.0f}ms)")
        return False


METHODS = {
    "trigger_wake_word": {
        "desc": "Wire-Pod API: /api-sdk/trigger_wake_word (simulates button press)",
        "fn": lambda r: test_trigger_wake_word(r),
        "level": 1,
    },
    "consolevars_button": {
        "desc": "Direct robot:8889 consolevarset FakeButtonPressType=singlePressDetected",
        "fn": lambda r: test_consolevars_button(r),
        "level": 2,
    },
    "cloud_intent_wake": {
        "desc": "Wire-Pod cloud_intent: intent_system_wake (undocumented)",
        "fn": lambda r: test_cloud_intent(r, "intent_system_wake"),
        "level": 3,
    },
    "cloud_intent_hello": {
        "desc": "Wire-Pod cloud_intent: intent_greeting_hello",
        "fn": lambda r: test_cloud_intent(r, "intent_greeting_hello"),
        "level": 3,
    },
    "cloud_intent_charger_off": {
        "desc": "Wire-Pod cloud_intent: intent_system_charger_off",
        "fn": lambda r: test_cloud_intent(r, "intent_system_charger_off"),
        "level": 3,
    },
    "cloud_intent_play": {
        "desc": "Wire-Pod cloud_intent: intent_play_fistbump",
        "fn": lambda r: test_cloud_intent(r, "intent_play_fistbump"),
        "level": 3,
    },
}


def run_single(method_name: str):
    method = METHODS[method_name]
    print(f"{'='*60}")
    print(f"Testing: {method_name} (Level {method['level']})")
    print(f"Description: {method['desc']}")
    print(f"{'='*60}")
    print()

    env = check_reachable()
    robot = env.get("robot")
    if robot is None:
        print("[ABORT] Cannot connect to Vector")
        return

    print()
    sent = method["fn"](robot)
    print()

    if sent:
        woke = verify_wake(robot)
    else:
        woke = False
        print("[SKIP] Method failed — skipping verify")

    print()
    print(f"{'='*60}")
    print(f"RESULT: {method_name} → WOKE_VECTOR = {woke}")
    print(f"{'='*60}")

    try:
        robot.disconnect()
    except Exception:
        pass


def run_all():
    print("Running ALL wake methods sequentially")
    print("Vector should be SLEEPING on charger for meaningful results")
    print()

    env = check_reachable()
    robot = env.get("robot")
    if robot is None:
        print("[ABORT] Cannot connect to Vector")
        return

    results = {}
    for name, method in METHODS.items():
        print()
        print(f"{'='*60}")
        print(f"Testing: {name} (Level {method['level']})")
        print(f"{'='*60}")

        sent = method["fn"](robot)
        if sent:
            woke = verify_wake(robot)
        else:
            woke = False

        results[name] = woke

        if woke:
            print(f"[INFO] {name} WOKE Vector — releasing control for next test")
            try:
                robot.conn.release_control()
            except Exception:
                pass
            print("[INFO] Waiting 10s for Vector to go back to sleep...")
            time.sleep(10)

    try:
        robot.disconnect()
    except Exception:
        pass

    print()
    print(f"{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, woke in results.items():
        status = "WOKE_VECTOR = TRUE" if woke else "WOKE_VECTOR = FALSE"
        print(f"  {name:<30s} {status}")


def main():
    parser = argparse.ArgumentParser(description="Test wake methods via Wire-Pod API and robot debug port")
    parser.add_argument("--list", action="store_true", help="List available methods")
    parser.add_argument("--method", type=str, help="Single method to test")
    parser.add_argument("--all", action="store_true", help="Run all methods sequentially")
    args = parser.parse_args()

    if args.list:
        print("Available wake test methods:\n")
        for name, info in METHODS.items():
            print(f"  --method {name:<30s} [L{info['level']}] {info['desc']}")
        print(f"\n  --all                                Run all methods sequentially")
        return

    if args.all:
        run_all()
        return

    if args.method:
        if args.method not in METHODS:
            print(f"Unknown method: {args.method}")
            print("Use --list to see available methods.")
            sys.exit(1)
        run_single(args.method)
        return

    parser.print_help()


if __name__ == "__main__":
    main()