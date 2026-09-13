# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""Stress test suite for VectorControl web dashboard.

Runs via Playwright (Chromium) against a running server on port 4001.
Tests: wake, camera, all motor controls, speed presets, speech, go home,
rapid button presses, WebSocket stability, API responsiveness.

Usage: .venv/bin/python tools/stress_test.py
"""

import asyncio
import json
import sys
import time

import requests
import websockets
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4001"
WS_BASE = "ws://127.0.0.1:4001"
RESULTS = []


def log(test_name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((test_name, passed, detail))
    print(f"  [{status}] {test_name}" + (f" — {detail}" if detail else ""))


def test_api_status():
    print("\n=== TEST 1: API Status ===")
    try:
        r = requests.get(f"{BASE}/api/status", timeout=5)
        d = r.json()
        log("GET /api/status", r.status_code == 200, f"state={d.get('state')}")
        log("has firmware", bool(d.get("firmware")), d.get("firmware"))
        log("has battery", "battery_volts" in d, f"{d.get('battery_volts')}V")
    except Exception as e:
        log("API status", False, str(e))


def test_api_vector_state():
    print("\n=== TEST 2: Vector State ===")
    try:
        r = requests.get(f"{BASE}/api/vector_state", timeout=5)
        d = r.json()
        log("GET /api/vector_state", r.status_code == 200, f"state={d.get('state')}")
    except Exception as e:
        log("Vector state", False, str(e))


def test_wake():
    print("\n=== TEST 3: Wake ===")
    try:
        d = requests.get(f"{BASE}/api/vector_state", timeout=5).json()
        if d.get("has_control"):
            log("Already awake", True, "skipping wake")
            return

        r = requests.post(f"{BASE}/api/wake", timeout=5)
        log("POST /api/wake", r.status_code == 200, r.json())

        for i in range(20):
            time.sleep(1)
            d = requests.get(f"{BASE}/api/vector_state", timeout=5).json()
            if d.get("has_control"):
                log("Wake completed", True, f"{i+1}s")
                return
        log("Wake completed", False, "timeout 20s")
    except Exception as e:
        log("Wake", False, str(e))


def test_camera_websocket():
    print("\n=== TEST 4: Camera WebSocket ===")
    try:
        async def _test():
            async with websockets.connect(f"{WS_BASE}/ws/camera") as ws:
                frames = 0
                total_bytes = 0
                t0 = time.time()
                while time.time() - t0 < 5:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    frames += 1
                    total_bytes += len(msg)
                return frames, total_bytes

        frames, total_bytes = asyncio.run(_test())
        fps = frames / 5
        avg_size = total_bytes // max(frames, 1)
        log("Camera frames received", frames > 0, f"{frames} frames in 5s ({fps:.1f} FPS)")
        log("Camera FPS >= 5", fps >= 5, f"{fps:.1f} FPS")
        log("Frame size reasonable", 1000 < avg_size < 200000, f"avg {avg_size} bytes")
    except Exception as e:
        log("Camera WebSocket", False, str(e))


def test_telemetry_websocket():
    print("\n=== TEST 5: Telemetry WebSocket ===")
    try:
        async def _test():
            async with websockets.connect(f"{WS_BASE}/ws/telemetry") as ws:
                msgs = []
                t0 = time.time()
                while time.time() - t0 < 3:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    msgs.append(json.loads(msg))
                return msgs

        msgs = asyncio.run(_test())
        log("Telemetry messages received", len(msgs) > 0, f"{len(msgs)} in 3s")
        if msgs:
            keys = list(msgs[0].keys())
            log("Has battery data", "battery" in keys, str(keys))
            log("Has proximity", "proximity" in keys)
            log("Has pose", "pose" in keys)
            log("Has accel", "accel" in keys)
            log("Has gyro", "gyro" in keys)
    except Exception as e:
        log("Telemetry WebSocket", False, str(e))


def test_motor_apis():
    print("\n=== TEST 6: Motor APIs ===")
    actions = [
        ("drive forward", "POST", "/api/drive?action=forward"),
        ("drive stop", "POST", "/api/drive?action=stop"),
        ("drive backward", "POST", "/api/drive?action=backward"),
        ("drive stop", "POST", "/api/drive?action=stop"),
        ("drive left", "POST", "/api/drive?action=left"),
        ("drive stop", "POST", "/api/drive?action=stop"),
        ("drive right", "POST", "/api/drive?action=right"),
        ("drive stop", "POST", "/api/drive?action=stop"),
        ("head up", "POST", "/api/head?direction=up"),
        ("head stop", "POST", "/api/head/stop"),
        ("head down", "POST", "/api/head?direction=down"),
        ("head stop", "POST", "/api/head/stop"),
        ("lift up", "POST", "/api/lift?direction=up"),
        ("lift stop", "POST", "/api/lift/stop"),
        ("lift down", "POST", "/api/lift?direction=down"),
        ("lift stop", "POST", "/api/lift/stop"),
        ("emergency stop", "POST", "/api/stop"),
    ]
    for name, method, path in actions:
        try:
            t0 = time.time()
            r = requests.post(f"{BASE}{path}", timeout=5)
            dt = (time.time() - t0) * 1000
            log(name, r.status_code == 200, f"{dt:.0f}ms")
            time.sleep(0.3)
        except Exception as e:
            log(name, False, str(e))


def test_speed_presets():
    print("\n=== TEST 7: Speed Presets ===")
    for level in range(5):
        try:
            r = requests.post(f"{BASE}/api/speed?level={level}", timeout=5)
            d = r.json()
            log(f"Speed level {level}", d.get("ok"), f"{d.get('label')} {d.get('drive_mmps')}mm/s")
        except Exception as e:
            log(f"Speed level {level}", False, str(e))

    try:
        r = requests.get(f"{BASE}/api/speed", timeout=5)
        d = r.json()
        log("GET /api/speed", "presets" in d, f"{len(d.get('presets', []))} presets")
    except Exception as e:
        log("GET speed", False, str(e))


def test_rapid_commands():
    print("\n=== TEST 8: Rapid Command Stress ===")
    try:
        t0 = time.time()
        success = 0
        total = 50
        for i in range(total):
            action = ["forward", "backward", "left", "right", "stop"][i % 5]
            r = requests.post(f"{BASE}/api/drive?action={action}", timeout=3)
            if r.status_code == 200:
                success += 1
        dt = (time.time() - t0) * 1000
        log(f"Rapid commands ({total})", success == total, f"{success}/{total} OK in {dt:.0f}ms ({dt/total:.0f}ms avg)")
    except Exception as e:
        log("Rapid commands", False, str(e))

    requests.post(f"{BASE}/api/stop", timeout=5)


def test_server_stability():
    print("\n=== TEST 9: Server Stability After Stress ===")
    try:
        r = requests.get(f"{BASE}/api/status", timeout=5)
        d = r.json()
        log("Server responsive", r.status_code == 200)
        log("Still connected", d.get("connected", False))
        log("Still has control", d.get("has_control", False))
    except Exception as e:
        log("Server stability", False, str(e))


def test_playwright_ui():
    print("\n=== TEST 10: Playwright UI Test ===")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            console_errors = []
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))

            page.goto(f"{BASE}")
            time.sleep(3)

            status = page.text_content("#connection-status") or ""
            log("UI shows ONLINE", "ONLINE" in status, status)

            wake_state = page.text_content("#wake-state") or ""
            log("UI shows AWAKE", "AWAKE" in wake_state, wake_state)

            fps = page.text_content("#fps") or ""
            log("UI shows FPS", "FPS" in fps, fps)

            ids = [
                "btn-fwd", "btn-back", "btn-left", "btn-right", "btn-stop",
                "btn-head-up", "btn-head-down", "btn-lift-up", "btn-lift-down",
                "btn-wake", "btn-release-control", "btn-go-home", "btn-off-charger",
                "speed-slider", "speech-input", "speech-btn",
            ]
            missing = [eid for eid in ids if not page.query_selector(f"#{eid}")]
            log("All UI elements present", len(missing) == 0, f"missing: {missing}" if missing else f"{len(ids)} elements OK")

            log("No JS errors", len(console_errors) == 0, f"{len(console_errors)} errors" if console_errors else "clean")

            # Test keyboard controls
            reqs = []
            page.on("request", lambda req: reqs.append(req.url) if "api/drive" in req.url else None)

            page.keyboard.down("w")
            time.sleep(0.5)
            page.keyboard.up("w")
            time.sleep(0.5)
            drive_reqs = [r for r in reqs if "drive" in r]
            log("Keyboard W sends drive", len(drive_reqs) >= 2, f"{len(drive_reqs)} requests")

            browser.close()
    except Exception as e:
        log("Playwright UI", False, str(e))


def test_go_home():
    print("\n=== TEST 11: Go Home ===")
    try:
        r = requests.post(f"{BASE}/api/go_home", timeout=5)
        log("POST /api/go_home", r.status_code == 200, r.json())
        time.sleep(8)
        d = requests.get(f"{BASE}/api/status", timeout=5).json()
        log("Server alive after go_home", d.get("connected", False))
    except Exception as e:
        log("Go home", False, str(e))


def main():
    print("=" * 60)
    print("VECTORCONTROL STRESS TEST SUITE")
    print("=" * 60)

    r = requests.get(f"{BASE}/api/status", timeout=5)
    if r.status_code != 200:
        print("Server not running on port 4001!")
        sys.exit(1)

    test_api_status()
    test_api_vector_state()
    test_wake()
    test_camera_websocket()
    test_telemetry_websocket()
    test_motor_apis()
    test_speed_presets()
    test_rapid_commands()
    test_server_stability()
    test_playwright_ui()
    test_go_home()

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    for name, p, detail in RESULTS:
        if not p:
            print(f"  FAIL: {name} — {detail}")
    print(f"\n  {passed} passed, {failed} failed, {len(RESULTS)} total")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
