#!/usr/bin/env python3
"""Test individual wake methods against Vector.

Usage:
    .venv/bin/python tools/test_wake_methods.py --list
    .venv/bin/python tools/test_wake_methods.py --method intent_wake
    .venv/bin/python tools/test_wake_methods.py --method intent_hello
    .venv/bin/python tools/test_wake_methods.py --method intent_explore
    .venv/bin/python tools/test_wake_methods.py --method control
    .venv/bin/python tools/test_wake_methods.py --method battery
"""

import argparse
import sys
import time

import anki_vector
from anki_vector.messaging import protocol

SERIAL = "00401c2e"


def connect_observation():
    print("[CONNECT] Connecting in observation mode (no behavior control)...")
    robot = anki_vector.Robot(serial=SERIAL, behavior_control_level=None)
    robot.connect(timeout=15)
    print("[CONNECT] Connected.")
    return robot


def disconnect(robot):
    try:
        robot.disconnect()
    except Exception:
        pass
    print("[DISCONNECT] Done.")


def test_battery(robot):
    """Read battery state — works without control, verifies gRPC is alive."""
    print("[TEST] battery: calling get_battery_state()...")
    t0 = time.time()
    bat = robot.get_battery_state()
    dt = (time.time() - t0) * 1000
    print(f"[TEST] battery: level={bat.battery_level}, volts={bat.battery_volts:.2f}V, "
          f"charging={bat.is_charging}, on_charger={bat.is_on_charger_platform} ({dt:.0f}ms)")
    return True


def test_intent(robot, intent_name):
    """Send an app_intent — does NOT require behavior control."""
    print(f"[TEST] intent: sending app_intent('{intent_name}')...")
    t0 = time.time()
    try:
        result = robot.behavior.app_intent(intent=intent_name)
        dt = (time.time() - t0) * 1000
        print(f"[TEST] intent: response = {result} ({dt:.0f}ms)")
        return True
    except Exception as exc:
        dt = (time.time() - t0) * 1000
        print(f"[TEST] intent: FAILED — {type(exc).__name__}: {exc} ({dt:.0f}ms)")
        return False


def test_control(robot, timeout=5):
    """Try to request behavior control — blocks up to timeout seconds."""
    print(f"[TEST] control: calling request_control(timeout={timeout})...")
    t0 = time.time()
    try:
        robot.conn.request_control(timeout=timeout)
        dt = (time.time() - t0) * 1000
        print(f"[TEST] control: GRANTED ({dt:.0f}ms)")
        print("[TEST] control: releasing control...")
        robot.conn.release_control()
        print("[TEST] control: released.")
        return True
    except Exception as exc:
        dt = (time.time() - t0) * 1000
        print(f"[TEST] control: FAILED — {type(exc).__name__}: {exc} ({dt:.0f}ms)")
        return False


METHODS = {
    "battery": {
        "desc": "Read battery state (no control needed, verifies gRPC)",
        "fn": lambda r: test_battery(r),
    },
    "intent_wake": {
        "desc": "app_intent('intent_system_wake') — undocumented, may wake Vector",
        "fn": lambda r: test_intent(r, "intent_system_wake"),
    },
    "intent_hello": {
        "desc": "app_intent('intent_greeting_hello') — may trigger greeting",
        "fn": lambda r: test_intent(r, "intent_greeting_hello"),
    },
    "intent_explore": {
        "desc": "app_intent('intent_system_charger_off') — may drive off charger",
        "fn": lambda r: test_intent(r, "intent_system_charger_off"),
    },
    "intent_sleep": {
        "desc": "app_intent('intent_system_sleep') — puts Vector to sleep (documented)",
        "fn": lambda r: test_intent(r, "intent_system_sleep"),
    },
    "intent_play": {
        "desc": "app_intent('intent_play_fistbump') — may trigger play behavior",
        "fn": lambda r: test_intent(r, "intent_play_fistbump"),
    },
    "intent_weather": {
        "desc": "app_intent('intent_weather_extend') — may trigger weather check",
        "fn": lambda r: test_intent(r, "intent_weather_extend"),
    },
    "control": {
        "desc": "request_control(timeout=5) — blocks if Vector sleeps",
        "fn": lambda r: test_control(r, timeout=5),
    },
    "control_long": {
        "desc": "request_control(timeout=30) — longer timeout",
        "fn": lambda r: test_control(r, timeout=30),
    },
}


def main():
    parser = argparse.ArgumentParser(description="Test individual wake methods for Vector")
    parser.add_argument("--list", action="store_true", help="List available methods")
    parser.add_argument("--method", type=str, help="Method to test")
    args = parser.parse_args()

    if args.list:
        print("Available wake test methods:\n")
        for name, info in METHODS.items():
            print(f"  --method {name:<20s} {info['desc']}")
        print(f"\nUsage: .venv/bin/python tools/test_wake_methods.py --method <name>")
        return

    if not args.method:
        parser.print_help()
        return

    if args.method not in METHODS:
        print(f"Unknown method: {args.method}")
        print(f"Use --list to see available methods.")
        sys.exit(1)

    method = METHODS[args.method]
    print(f"=== Testing: {args.method} ===")
    print(f"Description: {method['desc']}")
    print()

    robot = connect_observation()

    try:
        test_battery(robot)
        print()
        ok = method["fn"](robot)
        print()
        if args.method.startswith("intent"):
            print("[POST-CHECK] Waiting 3 seconds for Vector to react...")
            time.sleep(3)
            test_battery(robot)
        print()
        print(f"=== Result: {'SUCCESS' if ok else 'FAILED'} ===")
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
    finally:
        disconnect(robot)


if __name__ == "__main__":
    main()
