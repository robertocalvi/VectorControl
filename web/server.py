# VectorControl — Anki Vector Robot Controller
# Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
# Email: roberto@calvitecnologie.it
# License: MIT (see LICENSE file)

"""VectorControl Web Portal — FastAPI backend.

Provides:
- MJPEG camera stream via WebSocket
- Motor control endpoints (drive, head, lift, stop)
- Telemetry WebSocket (battery, proximity, pose, accel, gyro)
- Text-to-speech endpoint
- Static file serving for the dashboard UI
- Wake state machine via VectorManager (/api/wake)

Run: .venv/bin/python web/server.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import signal
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from vectorcontrol.vector_manager import VectorManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vectorcontrol.web")

manager = VectorManager(serial="00401c2e")

SPEED_PRESETS = [
    (40,   25,  "CAUTO"),
    (80,   50,  "LENTO"),
    (130,  80,  "MEDIO"),
    (180,  120, "VELOCE"),
    (220,  160, "MAX"),
]
_speed_level: int = 1
HEAD_SPEED = 5.0
LIFT_SPEED = 5.0

_head_angle_deg: float = 0.0
_lift_height: float = 0.0


def _drive_speed() -> int:
    return SPEED_PRESETS[_speed_level][0]


def _turn_speed() -> int:
    return SPEED_PRESETS[_speed_level][1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(manager.connect)
    yield
    await asyncio.to_thread(manager.disconnect)


app = FastAPI(title="VectorControl", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


_reconnect_lock = asyncio.Lock()
_reconnecting = False


async def _auto_reconnect():
    global _reconnecting
    if _reconnecting:
        return
    async with _reconnect_lock:
        if _reconnecting:
            return
        _reconnecting = True
        try:
            logger.info("Auto-reconnect: connection lost, reconnecting...")
            await asyncio.to_thread(manager.disconnect)
            await asyncio.sleep(2)
            await asyncio.to_thread(manager.connect)
            logger.info("Auto-reconnect: reconnected successfully")
        except Exception as exc:
            logger.warning("Auto-reconnect failed: %s", exc)
        finally:
            _reconnecting = False


@app.get("/api/status")
async def api_status():
    robot = manager.robot
    if robot is None:
        return JSONResponse({"connected": False, **manager.state.to_dict()}, status_code=503)
    try:
        bat = await asyncio.to_thread(robot.get_battery_state)
        ver = await asyncio.to_thread(robot.get_version_state)
        return {
            "connected": True,
            **manager.state.to_dict(),
            "firmware": ver.os_version,
            "battery_level": bat.battery_level,
            "battery_volts": round(bat.battery_volts, 2),
            "is_charging": bat.is_charging,
            "is_on_charger": bat.is_on_charger_platform,
        }
    except Exception as exc:
        asyncio.create_task(_auto_reconnect())
        return JSONResponse(
            {"connected": False, "error": str(exc), **manager.state.to_dict()},
            status_code=500,
        )


@app.get("/api/vector_state")
async def api_vector_state():
    return manager.state.to_dict()


@app.post("/api/wake")
async def api_wake():
    """Start wake sequence in background. Returns immediately."""
    if manager.robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    started = manager.wake(timeout=30)
    return {"ok": True, "started": started, **manager.state.to_dict()}


@app.post("/api/take_control")
async def api_take_control():
    return await api_wake()


@app.post("/api/release_control")
async def api_release_control():
    if manager.robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    await asyncio.to_thread(manager.release)
    return {"ok": True, **manager.state.to_dict()}


@app.post("/api/drive")
async def api_drive(action: str = "stop"):
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        ds = _drive_speed()
        ts = _turn_speed()
        if action == "forward":
            await asyncio.to_thread(robot.motors.set_wheel_motors, ds, ds)
        elif action == "backward":
            await asyncio.to_thread(robot.motors.set_wheel_motors, -ds, -ds)
        elif action == "left":
            await asyncio.to_thread(robot.motors.set_wheel_motors, -ts, ts)
        elif action == "right":
            await asyncio.to_thread(robot.motors.set_wheel_motors, ts, -ts)
        else:
            await asyncio.to_thread(robot.motors.set_wheel_motors, 0, 0)
        return {"ok": True, "action": action, "drive_speed": ds, "turn_speed": ts}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/head")
async def api_head(direction: str = "stop"):
    global _head_angle_deg
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        if direction == "up":
            _head_angle_deg = min(_head_angle_deg + 5, 45)
        elif direction == "down":
            _head_angle_deg = max(_head_angle_deg - 5, -22)
        speed = HEAD_SPEED if direction == "up" else (-HEAD_SPEED if direction == "down" else 0)
        await asyncio.to_thread(robot.motors.set_head_motor, speed)
        return {"ok": True, "head_angle_deg": _head_angle_deg}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/head/stop")
async def api_head_stop():
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if manager.has_control:
            await asyncio.to_thread(robot.motors.set_head_motor, 0)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lift")
async def api_lift(direction: str = "stop"):
    global _lift_height
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        speed = LIFT_SPEED if direction == "up" else (-LIFT_SPEED if direction == "down" else 0)
        await asyncio.to_thread(robot.motors.set_lift_motor, speed)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lift/stop")
async def api_lift_stop():
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if manager.has_control:
            await asyncio.to_thread(robot.motors.set_lift_motor, 0)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/speed")
async def api_speed(level: int = 1):
    global _speed_level
    _speed_level = max(0, min(level, len(SPEED_PRESETS) - 1))
    preset = SPEED_PRESETS[_speed_level]
    return {"ok": True, "level": _speed_level, "drive_mmps": preset[0], "turn_mmps": preset[1], "label": preset[2]}


@app.get("/api/speed")
async def api_speed_get():
    preset = SPEED_PRESETS[_speed_level]
    return {
        "level": _speed_level,
        "drive_mmps": preset[0],
        "turn_mmps": preset[1],
        "label": preset[2],
        "presets": [{"level": i, "drive": p[0], "turn": p[1], "label": p[2]} for i, p in enumerate(SPEED_PRESETS)],
    }


@app.post("/api/go_home")
async def api_go_home():
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        threading.Thread(target=robot.behavior.drive_on_charger, daemon=True).start()
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/drive_off_charger")
async def api_drive_off_charger():
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        threading.Thread(target=robot.behavior.drive_off_charger, daemon=True).start()
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/stop")
async def api_stop():
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if manager.has_control:
            await asyncio.to_thread(robot.motors.stop_all_motors)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/say")
async def api_say(text: str = "Hello"):
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        await asyncio.to_thread(robot.behavior.say_text, text)
        return {"ok": True, "text": text}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/quick_action")
async def api_quick_action(action: str = "say_hello"):
    robot = manager.robot
    if robot is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        manager.ensure_control()
        if action == "say_hello":
            await asyncio.to_thread(robot.behavior.say_text, "Hello! I am Vector!")
        elif action == "be_happy":
            await asyncio.to_thread(robot.behavior.say_text, "I am so happy!")
        elif action == "look_around":
            await asyncio.to_thread(robot.motors.set_head_motor, 3.0)
            await asyncio.sleep(1)
            await asyncio.to_thread(robot.motors.set_wheel_motors, 60, -60)
            await asyncio.sleep(2)
            await asyncio.to_thread(robot.motors.stop_all_motors)
        elif action == "play_animation":
            await asyncio.to_thread(robot.behavior.say_text, "Watch this!")
        elif action == "take_photo":
            await asyncio.to_thread(robot.behavior.say_text, "Cheese!")
        else:
            return JSONResponse({"error": f"unknown action: {action}"}, status_code=400)
        return {"ok": True, "action": action}
    except Exception as exc:
        logger.warning("Quick action %s failed: %s", action, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


_camera_error_logged = False


def _grab_camera_frame() -> str | None:
    global _camera_error_logged
    robot = manager.robot
    if robot is None or not manager.has_control:
        return None
    try:
        img = robot.camera.latest_image
        if img and img.raw_image:
            buf = io.BytesIO()
            img.raw_image.save(buf, format="JPEG", quality=60)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        if not _camera_error_logged:
            logger.warning("Camera frame error: %s", exc)
            _camera_error_logged = True
    return None


@app.websocket("/ws/camera")
async def ws_camera(ws: WebSocket):
    await ws.accept()
    logger.info("Camera WebSocket connected")
    try:
        while True:
            if manager.robot is None:
                await asyncio.sleep(1)
                continue
            try:
                b64 = await asyncio.to_thread(_grab_camera_frame)
                if b64:
                    await ws.send_text(b64)
            except Exception:
                pass
            await asyncio.sleep(0.1)
    except (WebSocketDisconnect, Exception):
        logger.info("Camera WebSocket disconnected")


def _collect_telemetry() -> dict:
    robot = manager.robot
    if robot is None:
        return {}
    data: dict = {}
    data["wake_state"] = manager.state.state.value
    try:
        bat = robot.get_battery_state()
        data["battery"] = {
            "level": bat.battery_level,
            "volts": round(bat.battery_volts, 2),
            "charging": bat.is_charging,
            "on_charger": bat.is_on_charger_platform,
        }
    except Exception:
        pass
    try:
        prox = robot.proximity.last_sensor_reading
        if prox:
            data["proximity"] = {
                "distance_mm": round(prox.distance.distance_mm, 1),
                "found_object": prox.found_object,
                "signal_quality": round(prox.signal_quality, 2),
                "unobstructed": prox.unobstructed,
            }
    except Exception:
        pass
    try:
        pose = robot.pose
        if pose:
            data["pose"] = {
                "x": round(pose.position.x, 1),
                "y": round(pose.position.y, 1),
                "z": round(pose.position.z, 1),
                "angle_deg": round(pose.rotation.angle_z.degrees, 1),
            }
    except Exception:
        pass
    try:
        accel = robot.accel
        if accel:
            data["accel"] = {
                "x": round(accel.x, 2),
                "y": round(accel.y, 2),
                "z": round(accel.z, 2),
            }
    except Exception:
        pass
    try:
        gyro = robot.gyro
        if gyro:
            data["gyro"] = {
                "x": round(gyro.x, 2),
                "y": round(gyro.y, 2),
                "z": round(gyro.z, 2),
            }
    except Exception:
        pass
    try:
        data["head_angle_rad"] = round(robot.head_angle_rad, 3)
        data["lift_height_mm"] = round(robot.lift_height_mm, 1)
    except Exception:
        pass
    return data


@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    logger.info("Telemetry WebSocket connected")
    try:
        while True:
            if manager.robot is None:
                await asyncio.sleep(1)
                continue
            try:
                data = await asyncio.to_thread(_collect_telemetry)
                await ws.send_text(json.dumps(data))
            except Exception:
                pass
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception):
        logger.info("Telemetry WebSocket disconnected")


if __name__ == "__main__":
    def _shutdown(sig, frame):
        logger.info("Shutting down …")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    uvicorn.run(
        "web.server:app",
        host="127.0.0.1",
        port=4001,
        log_level="info",
        reload=False,
    )