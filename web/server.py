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
_has_control: bool = False

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
    """Connect to Vector in observation mode (no behavior control). Starts instantly even if Vector is asleep."""
    global ROBOT, _has_control
    logger.info("Connecting to Vector (serial=%s) in observation mode …", SERIAL)
    robot = anki_vector.Robot(serial=SERIAL, behavior_control_level=None)
    robot.connect(timeout=15)
    robot.camera.init_camera_feed()
    ROBOT = robot
    _has_control = False
    logger.info("Connected (observation mode) — firmware %s", robot.get_version_state().os_version)
    return robot


_control_requesting: bool = False


def request_control() -> bool:
    global _has_control, _control_requesting
    if ROBOT is None:
        return False
    if _has_control:
        return True
    if _control_requesting:
        return False
    _control_requesting = True
    try:
        logger.info("Requesting behavior control …")
        ROBOT.conn.request_control(timeout=5)
        _has_control = True
        logger.info("Behavior control granted")
        return True
    except Exception as exc:
        logger.warning("Failed to get control: %s", exc)
        return False
    finally:
        _control_requesting = False


def release_control() -> None:
    """Release behavior control back to Vector."""
    global _has_control
    if ROBOT is None or not _has_control:
        return
    try:
        ROBOT.conn.release_control()
        _has_control = False
        logger.info("Behavior control released")
    except Exception:
        pass


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
        bat = await asyncio.to_thread(ROBOT.get_battery_state)
        ver = await asyncio.to_thread(ROBOT.get_version_state)
        return {
            "connected": True,
            "has_control": _has_control,
            "firmware": ver.os_version,
            "battery_level": bat.battery_level,
            "battery_volts": round(bat.battery_volts, 2),
            "is_charging": bat.is_charging,
            "is_on_charger": bat.is_on_charger_platform,
        }
    except Exception as exc:
        return JSONResponse({"connected": False, "error": str(exc)}, status_code=500)


@app.post("/api/take_control")
async def api_take_control():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    ok = await asyncio.to_thread(request_control)
    return {"ok": ok, "has_control": _has_control}


@app.post("/api/release_control")
async def api_release_control():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    await asyncio.to_thread(release_control)
    return {"ok": True, "has_control": _has_control}


# ---------------------------------------------------------------------------
# Motor control
# ---------------------------------------------------------------------------
def _ensure_control():
    if not _has_control:
        raise RuntimeError("No behavior control. Press TAKE CONTROL first (Vector must be awake).")


@app.post("/api/drive")
async def api_drive(action: str = "stop"):
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        await asyncio.to_thread(_ensure_control)
        ds = _drive_speed()
        ts = _turn_speed()
        if action == "forward":
            await asyncio.to_thread(ROBOT.motors.set_wheel_motors, ds, ds)
        elif action == "backward":
            await asyncio.to_thread(ROBOT.motors.set_wheel_motors, -ds, -ds)
        elif action == "left":
            await asyncio.to_thread(ROBOT.motors.set_wheel_motors, -ts, ts)
        elif action == "right":
            await asyncio.to_thread(ROBOT.motors.set_wheel_motors, ts, -ts)
        else:
            await asyncio.to_thread(ROBOT.motors.set_wheel_motors, 0, 0)
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
        await asyncio.to_thread(_ensure_control)
        if direction == "up":
            _head_angle_deg = min(_head_angle_deg + 5, 45)
        elif direction == "down":
            _head_angle_deg = max(_head_angle_deg - 5, -22)
        speed = HEAD_SPEED if direction == "up" else (-HEAD_SPEED if direction == "down" else 0)
        await asyncio.to_thread(ROBOT.motors.set_head_motor, speed)
        return {"ok": True, "head_angle_deg": _head_angle_deg}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/head/stop")
async def api_head_stop():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if _has_control:
            await asyncio.to_thread(ROBOT.motors.set_head_motor, 0)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lift")
async def api_lift(direction: str = "stop"):
    global _lift_height
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        await asyncio.to_thread(_ensure_control)
        speed = LIFT_SPEED if direction == "up" else (-LIFT_SPEED if direction == "down" else 0)
        await asyncio.to_thread(ROBOT.motors.set_lift_motor, speed)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lift/stop")
async def api_lift_stop():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        if not _has_control:
            return {"ok": True}
        await asyncio.to_thread(ROBOT.motors.set_lift_motor, 0)
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
        await asyncio.to_thread(_ensure_control)
        threading.Thread(target=ROBOT.behavior.drive_on_charger, daemon=True).start()
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/drive_off_charger")
async def api_drive_off_charger():
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        await asyncio.to_thread(_ensure_control)
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
        if _has_control:
            await asyncio.to_thread(ROBOT.motors.stop_all_motors)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/say")
async def api_say(text: str = "Hello"):
    if ROBOT is None:
        return JSONResponse({"error": "not connected"}, status_code=503)
    try:
        await asyncio.to_thread(_ensure_control)
        await asyncio.to_thread(ROBOT.behavior.say_text, text)
        return {"ok": True, "text": text}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# WebSocket — camera stream (base64 JPEG frames)
# ---------------------------------------------------------------------------
def _grab_camera_frame() -> str | None:
    try:
        img = ROBOT.camera.latest_image
        if img and img.raw_image:
            buf = io.BytesIO()
            img.raw_image.save(buf, format="JPEG", quality=60)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        pass
    return None


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
                b64 = await asyncio.to_thread(_grab_camera_frame)
                if b64:
                    await ws.send_text(b64)
            except Exception:
                pass
            await asyncio.sleep(0.1)
    except (WebSocketDisconnect, Exception):
        logger.info("Camera WebSocket disconnected")


# ---------------------------------------------------------------------------
# WebSocket — telemetry stream (JSON)
# ---------------------------------------------------------------------------
def _collect_telemetry() -> dict:
    """Collect all telemetry data (runs in a thread to avoid blocking asyncio)."""
    data: dict = {}
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
    try:
        data["head_angle_rad"] = round(ROBOT.head_angle_rad, 3)
        data["lift_height_mm"] = round(ROBOT.lift_height_mm, 1)
    except Exception:
        pass
    return data


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
                data = await asyncio.to_thread(_collect_telemetry)
                await ws.send_text(json.dumps(data))
            except Exception:
                pass
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception):
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
        host="127.0.0.1",
        port=4001,
        log_level="info",
        reload=False,
    )
