"""VectorControl Web Portal — FastAPI backend.

Provides:
- MJPEG camera stream via WebSocket
- Motor control endpoints (drive, head, lift, stop)
- Telemetry WebSocket (battery, proximity, pose, accel, gyro)
- Text-to-speech endpoint
- Static file serving for the dashboard UI

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
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import anki_vector
from anki_vector.util import degrees, distance_mm, speed_mmps
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vectorcontrol.web")

# ---------------------------------------------------------------------------
# Global robot state
# ---------------------------------------------------------------------------
ROBOT: anki_vector.Robot | None = None
ROBOT_LOCK = threading.Lock()
SERIAL = "00401c2e"

# Speed presets: (drive_mmps, turn_mmps, label)
SPEED_PRESETS = [
    (40,   25,  "CAUTO"),
    (80,   50,  "LENTO"),
    (130,  80,  "MEDIO"),
    (180,  120, "VELOCE"),
    (220,  160, "MAX"),
]
_speed_level: int = 1  # default: LENTO
HEAD_SPEED = 5.0       # rad/s
LIFT_SPEED = 5.0       # rad/s


def _drive_speed() -> int:
    return SPEED_PRESETS[_speed_level][0]


def _turn_speed() -> int:
    return SPEED_PRESETS[_speed_level][1]

# Current head/lift targets (degrees / fraction)
_head_angle_deg: float = 0.0
_lift_height: float = 0.0


def connect_robot() -> anki_vector.Robot:
    """Connect to Vector (blocking)."""
    global ROBOT
    logger.info("Connecting to Vector (serial=%s) …", SERIAL)
    robot = anki_vector.Robot(serial=SERIAL, behavior_activation_timeout=30)
    robot.connect(timeout=30)
    robot.camera.init_camera_feed()
    ROBOT = robot
    logger.info("Connected — firmware %s", robot.get_version_state().os_version)
    return robot


def disconnect_robot() -> None:
    """Safely disconnect."""
    global ROBOT
    if ROBOT is None:
        return
    try:
        ROBOT.motors.stop_all_motors()
    except Exception:
        pass
    try:
        ROBOT.camera.close_camera_feed()
    except Exception:
        pass
    try:
        ROBOT.disconnect()
    except Exception:
        pass
    ROBOT = None
    logger.info("Disconnected from Vector")


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    connect_robot()
    yield
    disconnect_robot()


app = FastAPI(title="VectorControl", lifespan=lifespan)

# Static files
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/status")
async def api_status():
    if ROBOT is None:
        return JSONResponse({"connected": False}, status_code=503)
    try:
        bat = ROBOT.get_battery_state()
        ver = ROBOT.get_version_state()
        return {
            "connected": True,
            "firmware": ver.os_version,
            "battery_level": bat.battery_level,
            "battery_volts": round(bat.battery_volts, 2),
            "is_charging": bat.is_charging,
            "is_on_charger": bat.is_on_charger_platform,
        }
    except Exception as exc:
        return JSONResponse({"connected": False, "error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Motor control
# ---------------------------------------------------------------------------
@app.post("/api/drive")
async def api_drive(action: str = "stop"):
    """Drive wheels.  action: forward | backward | left | right | stop"""
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        ds = _drive_speed()
        ts = _turn_speed()
        if action == "forward":
            ROBOT.motors.set_wheel_motors(ds, ds)
        elif action == "backward":
            ROBOT.motors.set_wheel_motors(-ds, -ds)
        elif action == "left":
            ROBOT.motors.set_wheel_motors(-ts, ts)
        elif action == "right":
            ROBOT.motors.set_wheel_motors(ts, -ts)
        else:
            ROBOT.motors.set_wheel_motors(0, 0)
        return {"ok": True, "action": action, "drive_speed": ds, "turn_speed": ts}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/head")
async def api_head(direction: str = "stop"):
    """Move head.  direction: up | down | stop"""
    global _head_angle_deg
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if direction == "up":
            _head_angle_deg = min(_head_angle_deg + 5, 45)
        elif direction == "down":
            _head_angle_deg = max(_head_angle_deg - 5, -22)
        else:
            pass  # keep current
        ROBOT.motors.set_head_motor(HEAD_SPEED if direction == "up" else (-HEAD_SPEED if direction == "down" else 0))
        return {"ok": True, "head_angle_deg": _head_angle_deg}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/head/stop")
async def api_head_stop():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        ROBOT.motors.set_head_motor(0)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lift")
async def api_lift(direction: str = "stop"):
    """Move lift.  direction: up | down | stop"""
    global _lift_height
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if direction == "up":
            ROBOT.motors.set_lift_motor(LIFT_SPEED)
        elif direction == "down":
            ROBOT.motors.set_lift_motor(-LIFT_SPEED)
        else:
            ROBOT.motors.set_lift_motor(0)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lift/stop")
async def api_lift_stop():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        ROBOT.motors.set_lift_motor(0)
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
    return {"level": _speed_level, "drive_mmps": preset[0], "turn_mmps": preset[1], "label": preset[2],
            "presets": [{"level": i, "drive": p[0], "turn": p[1], "label": p[2]} for i, p in enumerate(SPEED_PRESETS)]}


@app.post("/api/go_home")
async def api_go_home():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        threading.Thread(target=ROBOT.behavior.drive_on_charger, daemon=True).start()
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/drive_off_charger")
async def api_drive_off_charger():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        threading.Thread(target=ROBOT.behavior.drive_off_charger, daemon=True).start()
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/stop")
async def api_stop():
    """Emergency stop — all motors."""
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        ROBOT.motors.stop_all_motors()
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/say")
async def api_say(text: str = "Hello"):
    """Make Vector speak."""
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        ROBOT.behavior.say_text(text)
        return {"ok": True, "text": text}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# WebSocket — camera stream (base64 JPEG frames)
# ---------------------------------------------------------------------------
@app.websocket("/ws/camera")
async def ws_camera(ws: WebSocket):
    await ws.accept()
    logger.info("Camera WebSocket connected")
    try:
        while True:
            if ROBOT is None:
                await asyncio.sleep(1)
                continue
            try:
                img = ROBOT.camera.latest_image
                if img and img.raw_image:
                    buf = io.BytesIO()
                    img.raw_image.save(buf, format="JPEG", quality=60)
                    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    await ws.send_text(b64)
            except Exception:
                pass
            await asyncio.sleep(0.1)  # ~10 fps
    except WebSocketDisconnect:
        logger.info("Camera WebSocket disconnected")


# ---------------------------------------------------------------------------
# WebSocket — telemetry stream (JSON)
# ---------------------------------------------------------------------------
@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    logger.info("Telemetry WebSocket connected")
    try:
        while True:
            if ROBOT is None:
                await asyncio.sleep(1)
                continue
            try:
                data: dict = {}

                # Battery
                try:
                    bat = ROBOT.get_battery_state()
                    data["battery"] = {
                        "level": bat.battery_level,
                        "volts": round(bat.battery_volts, 2),
                        "charging": bat.is_charging,
                        "on_charger": bat.is_on_charger_platform,
                    }
                except Exception:
                    pass

                # Proximity
                try:
                    prox = ROBOT.proximity.last_sensor_reading
                    if prox:
                        data["proximity"] = {
                            "distance_mm": round(prox.distance.distance_mm, 1),
                            "found_object": prox.found_object,
                            "signal_quality": round(prox.signal_quality, 2),
                            "unobstructed": prox.unobstructed,
                        }
                except Exception:
                    pass

                # Pose
                try:
                    pose = ROBOT.pose
                    if pose:
                        data["pose"] = {
                            "x": round(pose.position.x, 1),
                            "y": round(pose.position.y, 1),
                            "z": round(pose.position.z, 1),
                            "angle_deg": round(pose.rotation.angle_z.degrees, 1),
                        }
                except Exception:
                    pass

                # Accelerometer
                try:
                    accel = ROBOT.accel
                    if accel:
                        data["accel"] = {
                            "x": round(accel.x, 2),
                            "y": round(accel.y, 2),
                            "z": round(accel.z, 2),
                        }
                except Exception:
                    pass

                # Gyro
                try:
                    gyro = ROBOT.gyro
                    if gyro:
                        data["gyro"] = {
                            "x": round(gyro.x, 2),
                            "y": round(gyro.y, 2),
                            "z": round(gyro.z, 2),
                        }
                except Exception:
                    pass

                # Head / Lift
                try:
                    data["head_angle_rad"] = round(ROBOT.head_angle_rad, 3)
                    data["lift_height_mm"] = round(ROBOT.lift_height_mm, 1)
                except Exception:
                    pass

                await ws.send_text(json.dumps(data))
            except Exception:
                pass
            await asyncio.sleep(0.5)  # 2 Hz telemetry
    except WebSocketDisconnect:
        logger.info("Telemetry WebSocket disconnected")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    def _shutdown(sig, frame):
        logger.info("Shutting down …")
        disconnect_robot()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=4001,
        log_level="info",
        reload=False,
    )
