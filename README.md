# VectorControl

A modern Python application for controlling an original first-generation **Anki Vector** robot from a Mac, featuring a real-time web dashboard with live camera feed, WASD controls, telemetry, and text-to-speech.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![SDK](https://img.shields.io/badge/SDK-wirepod--vector--sdk%200.8.1-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

![VectorControl Dashboard](docs/images/dashboard-working.png)

## The Problem

Anki went bankrupt in 2019. Digital Dream Labs (DDL) acquired Vector but their cloud servers have been **unreliable since April 2023**. The original `anki-vector` Python SDK (v0.6.0) depends on those dead servers for authentication — making it **unusable** for most Vector owners in 2024-2026.

This project documents the complete journey of bringing a first-gen Vector back to life with a fully local, cloud-free setup.

## Hardware

| Detail | Value |
|--------|-------|
| Robot | Anki Vector (1st generation) |
| Model | 300-00059 |
| Name | Vector R1D2 |
| Serial | `00401c2e` |
| Original firmware | `v1.7.0.3412` |
| Updated firmware | `v2.0.1.6086ep` |

## Quick Start

> **Prerequisites:** Wire-Pod running, Vector authenticated (see setup guide below)

```bash
cd VectorControl
.venv/bin/python -m web.server
```

Open **http://localhost:4001** in your browser. That's it — you'll see the live camera feed and can start driving Vector immediately.

## What This Project Does

- **Web Dashboard** on `http://localhost:4001` with:
  - Live camera feed (640×360 MJPEG via WebSocket, ~10 FPS)
  - WASD keyboard + click controls for driving, head, and lift
  - 5-level speed control (40–220 mm/s)
  - Real-time telemetry (battery, proximity, pose, accelerometer, gyroscope)
  - Text-to-speech input
  - Go Home / Off Charger buttons
- **Terminal remote control** (`main.py`) using curses
- **Diagnostics tool** for troubleshooting connectivity
- **Modular architecture** ready for future extensions (autonomous navigation, ArUco markers, web UI improvements)

## Prerequisites: Installing Wire-Pod

<img src="docs/images/wirepod-logo.png" width="64" align="left" style="margin-right: 12px;" />

**[Wire-Pod](https://github.com/kercre123/wire-pod)** is a free, open-source replacement for Anki's dead cloud servers. It runs locally on your computer and handles voice commands, authentication, and SDK communication. **It is required** — without it, Vector cannot authenticate and the Python SDK cannot connect.

<br clear="left" />

### Installing Wire-Pod on macOS

1. Go to the [WirePod releases page](https://github.com/kercre123/WirePod/releases)
2. Download the latest **`WirePod-v*.dmg`** file (we used v1.2.18)
3. Open the DMG and drag **WirePod** to your Applications folder
4. Launch WirePod from Applications — macOS will warn about an unidentified developer
5. Go to **System Settings → Privacy & Security** and click **"Open Anyway"**
6. WirePod will ask permission to find devices on local networks → **Allow**
7. Open **http://localhost:8080** (or `http://YOUR_MAC_IP:8080`) in your browser

### Wire-Pod Initial Setup

On first launch, Wire-Pod shows a setup page:

- **Connection Method**: Select **"Escape Pod"** (recommended for production robots)
- **Speech-to-Text Language**: Choose your language (we chose Italian)
- Click **"Submit Settings"**

You'll see the Wire-Pod dashboard with icons for Server Settings, Bot Settings, Bot Setup, Custom Intents, Log, Version Info, and UI Settings.

![Wire-Pod Dashboard](docs/images/wirepod-connected.png)

### Important Notes

- Wire-Pod must be **running** whenever you want to use the Python SDK
- Vector and your Mac must be on the **same WiFi network**
- Wire-Pod uses port **8080** for its web interface and port **443** for robot communication
- If Wire-Pod stops, just relaunch it from Applications

---

## Setup Journey & Problems Encountered

### Problem 1: The Original SDK Is Dead

The official `anki-vector` PyPI package (v0.6.0, last updated May 2019) requires Anki's cloud servers for authentication. Those servers are **permanently offline**. Running `python -m anki_vector.configure` simply fails.

**Solution:** Use [`wirepod-vector-sdk`](https://pypi.org/project/wirepod-vector-sdk/) (v0.8.1) — a community fork maintained by [kercre123](https://github.com/kercre123/wirepod-vector-python-sdk). It installs under the same `anki_vector` namespace but works with [Wire-Pod](https://github.com/kercre123/wire-pod), a free local server replacement.

### Problem 2: Wire-Pod Requires EP Firmware

![Non-EP firmware error](docs/images/firmware-error.png)

Wire-Pod needs Vector to run **Escape Pod (EP) firmware** — a special build with `ep` suffix in the version string. Our Vector had standard firmware `v1.7.0.3412` (no `ep`).

The normal flow is:
1. Double-tap Vector's back button — he shows his name and a pairing key on screen
2. Put Vector in recovery mode (hold back button 15 seconds → `anki.com/v` screen)
3. Use [wpsetup.keriganc.com](https://wpsetup.keriganc.com) in Chrome to flash EP firmware via Bluetooth

#### What Vector shows on screen during pairing

After double-tapping the back button, Vector displays his name and waits for a PIN:

| Waiting for pairing | PIN displayed |
|:---:|:---:|
| ![Pairing mode](docs/images/vector-pairing-mode.png) | ![PIN display](docs/images/vector-pin-display.png) |

The `######` placeholders turn into a 6-digit PIN once Chrome initiates the Bluetooth connection. You must enter this PIN quickly — it times out after about 30 seconds.

**What went wrong:**
- The Bluetooth Web API pairing kept disconnecting when Vector entered recovery mode
- The site would show "ACTIVATE" but lose the Bluetooth connection before the firmware could be sent
- Chrome remembered stale Bluetooth pairings that interfered with new connections
- The "auto-setup flow" checkbox caused redirect loops

### Problem 3: Bluetooth Pairing Loop

After pairing via Chrome's Web Bluetooth, the setup page would either:
- Show the error *"A non EP firmware has been detected and you are not in recovery mode"* (when Vector was in normal mode)
- Lose the Bluetooth connection immediately (when Vector was in recovery mode)
- Loop between "PAIR WITH VECTOR" and "Vector has disconnected"

**Failed attempts:**
- Pairing in normal mode, then switching to recovery mode → connection lost
- Pairing in recovery mode directly → Chrome couldn't maintain the connection
- Removing Bluetooth pairing from macOS System Settings → Vector wasn't listed there (Web Bluetooth manages its own pairings)
- Using Chrome Incognito mode → same issue
- Using `chrome://bluetooth-internals` → "Forget" didn't resolve it

### Problem 4: The BLE Console Breakthrough

**Solution:** On wpsetup.keriganc.com, **unchecking "Enable auto-setup flow"** before entering the PIN revealed a hidden **BLE console** — a direct command-line interface to Vector over Bluetooth:

![BLE Console](docs/images/ble-console.png)

![BLE Console Commands](docs/images/ble-console-help.png)

```
[v5] R1D2$ help
wifi-connect    Connect Vector to a WiFi network.
wifi-scan       Get WiFi networks that Vector can scan.
wifi-ip         Get Vector's WiFi IPv4/IPv6 addresses.
ota-start       Tell Vector to start an OTA update with the given URL.
ota-progress    Get the current OTA progress.
status          Get status information from Vector.
...
```

We tried `ota-start` with several firmware URLs, but they all returned 404 or tiny error responses:
- `http://192.168.1.3:8080/api-sdk/get_ep_ota` → "robot not found in SDK info file" (Vector wasn't authenticated yet — chicken-and-egg problem)
- `http://wpsetup.keriganc.com/firmware/1.8.0.3344/full/lkg.ota` → 404
- `http://ota.techshop82.com/vector-ota/escapepod-prod-1.8.ota` → 404
- `http://ota.pvic.xyz/OSKR_EP_1.7.3_6016.ota` → 404

### Problem 5: The Solution — TechShop82

**What finally worked:** [vector.techshop82.com](https://vector.techshop82.com) — an alternative setup site that:
1. Has a **firmware dropdown** to select the EP version
2. Hosts the firmware files on its own servers
3. Handles the Bluetooth → WiFi → OTA flow more reliably

Steps that worked:
1. Open `https://vector.techshop82.com/html/main.html` in Chrome
2. Select **`2.0.1.6086ep`** from the firmware dropdown
3. Put Vector in recovery mode (`anki.com/v`)
4. Pair via Bluetooth
5. The site connected Vector to WiFi and pushed the firmware OTA
6. Vector rebooted with EP firmware
7. Re-paired and pressed **ACTIVATE** → "Vector setup is complete!"

#### What Vector and the browser show during firmware update

| Browser: "Updating Vector..." | Vector's screen: cloud sync icon |
|:---:|:---:|
| ![TechShop82 updating](docs/images/techshop82-updating.png) | ![Vector cloud update](docs/images/vector-cloud-update.png) |

The firmware download takes 3–10 minutes depending on WiFi speed. **Do not remove Vector from the charger** during this process.

#### Setup complete

![Setup Complete](docs/images/setup-complete.png)

After rebooting, Vector is running firmware `2.0.1.6086ep` and can be authenticated with Wire-Pod.

### Problem 6: SDK Certificate

After Wire-Pod authentication, the Python SDK still couldn't connect:

```
SSL_ERROR_SSL: CERTIFICATE_VERIFY_FAILED: self signed certificate
```

The SDK needs the robot's TLS certificate as a trusted root. Wire-Pod's `session-certs` endpoint returned "cert does not exist" because DDL's certificate servers are down.

**Solution:** Extract the certificate directly from the robot using OpenSSL:

```bash
echo | openssl s_client -connect 192.168.1.30:443 -servername Vector-R1D2 2>/dev/null \
  | openssl x509 -outform PEM > ~/.anki_vector/Vector-R1D2-00401c2e.cert
```

Then we hit `StatusCode.UNAUTHENTICATED: 401` — the GUID in `sdk_config.ini` was wrong. Wire-Pod's API exposes two GUIDs:
- `global_guid` — the Wire-Pod server's GUID (wrong)
- `robots[].guid` — the robot-specific GUID (correct)

Using the robot-specific GUID from `http://WIREPOD_IP:8080/api-sdk/get_sdk_info` fixed it.

![Wire-Pod Connected](docs/images/wirepod-connected.png)

### Problem 7: Observation Mode — Motors Don't Work

After connecting with `behavior_control_level=None` (observation mode), we tried to acquire control later with `request_control()` and patching SDK internal flags. The SDK accepted the commands silently (200 OK responses) but **Vector didn't move at all**.

**Root cause:** In observation mode, the SDK's BehaviorControl gRPC stream is never opened. Even after patching `_behavior_control_level` and `control_granted_event`, the robot ignores motor commands because it doesn't recognize the client as a valid controller.

**Solution:** After wake, **disconnect and reconnect** with `behavior_activation_timeout` (full behavior control mode). This opens the BehaviorControl stream properly and Vector responds to motor commands.

```python
# What DOESN'T work:
robot = Robot(serial='...', behavior_control_level=None)  # observation mode
robot.conn.request_control(timeout=5)  # control "granted" but...
robot.motors.set_wheel_motors(80, 80)  # Vector doesn't move!

# What WORKS:
robot = Robot(serial='...', behavior_activation_timeout=15)  # full control
robot.motors.set_wheel_motors(80, 80)  # Vector moves!
```

### Problem 8: Error 800 — Wire-Pod Connection Lost

![Error 800](docs/images/vector-error-800.png)

Vector displays **error 800** with `anki.bot/support` when it cannot reach Wire-Pod. This happens when:

1. **Wire-Pod is not running** — the app was closed or crashed
2. **gRPC connection conflict** — our Python SDK and Wire-Pod compete for Vector's gRPC connection. When the SDK process is killed with `kill -9`, zombie gRPC connections block Wire-Pod from reconnecting
3. **Wire-Pod needs restart** — sometimes Wire-Pod gets stuck and needs a force quit from Activity Monitor, then relaunch

**How to fix error 800:**

1. Check if Wire-Pod is running (look for the rocket icon in the menu bar)
2. If not running, launch WirePod from Applications
3. If running but Vector still shows 800:
   - Kill any Python processes using Vector: `pkill -9 -f web.server`
   - Force quit WirePod from Activity Monitor (Cmd+Space → "Activity Monitor" → find WirePod → Force Quit)
   - Relaunch WirePod
   - Press Vector's back button briefly to make him reconnect
4. If still stuck: hold Vector's back button for 15 seconds (power off), then press briefly to restart

### Problem 9: Deep Sleep on Charger

Vector goes into **deep sleep** when sitting on the charger for more than a few seconds. In deep sleep:

- The debug port (8889) stops responding
- `request_control()` blocks indefinitely
- `FakeButtonPress` wake stimulus may not work
- The SDK connection times out

**Workaround:** The wake sequence sends multiple `FakeButtonPress` bursts (3 rapid presses per attempt, up to 5 attempts). This works most of the time but can take 7-12 seconds from deep sleep. If wake fails, Vector needs a physical button press to restart.

### Final Working Configuration

```ini
# ~/.anki_vector/sdk_config.ini
[00401c2e]
cert = /Users/USERNAME/.anki_vector/Vector-R1D2-00401c2e.cert
ip = 192.168.1.30
name = Vector-R1D2
guid = <robot-specific-guid-from-wirepod>
```

### Working Dashboard

![VectorControl Dashboard Working](docs/images/dashboard-working.png)

## Requirements

- **Python 3.11** (3.10 also works; 3.13 untested with the SDK)
- **macOS** (tested on macOS 26 / Apple Silicon)
- **Wire-Pod** running locally ([install guide](https://github.com/kercre123/wire-pod/wiki/Installation))
- **Anki Vector** with EP firmware, authenticated with Wire-Pod
- **Google Chrome** (for initial Bluetooth setup — Safari doesn't support Web Bluetooth)

## Installation

```bash
# Clone
git clone https://github.com/robertocalvi/VectorControl.git
cd VectorControl

# Create virtual environment
python3.11 -m venv .venv

# Install dependencies
.venv/bin/pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your robot's serial, IP, and Wire-Pod IP
```

### SDK Configuration

The SDK needs a certificate and config file at `~/.anki_vector/`:

```bash
# Extract certificate from robot (replace IP with your Vector's IP)
mkdir -p ~/.anki_vector
echo | openssl s_client -connect YOUR_VECTOR_IP:443 -servername Vector-XXXX 2>/dev/null \
  | openssl x509 -outform PEM > ~/.anki_vector/Vector-XXXX-SERIAL.cert

# Get the robot GUID from Wire-Pod
curl http://YOUR_WIREPOD_IP:8080/api-sdk/get_sdk_info

# Create ~/.anki_vector/sdk_config.ini with the values above
```

## Usage

### Web Dashboard (recommended)

```bash
.venv/bin/python -m web.server
# Open http://localhost:4001
```

**Controls:**

| Key | Action |
|-----|--------|
| W / A / S / D | Drive forward / left / backward / right |
| ↑ / ↓ | Head up / down |
| R / F | Lift up / down |
| SPACE | Emergency stop |
| 1-5 | Speed level (Cauto → Max) |

### Terminal Remote Control

```bash
.venv/bin/python main.py
```

### Diagnostics

```bash
.venv/bin/python tools/vector_diagnostics.py
```

### Connection Test

```bash
.venv/bin/python tests/test_connection.py
```

### Movement Test

```bash
.venv/bin/python tests/test_robot.py
```

## Project Structure

```
VectorControl/
├── .env.example              # Environment template
├── .gitignore
├── README.md
├── requirements.txt          # wirepod-vector-sdk, python-dotenv, fastapi, uvicorn
├── TODO.md                   # Project tracking
│
├── vectorcontrol/            # Core library
│   ├── __init__.py
│   ├── config.py             # Configuration loader (.env + sdk_config.ini)
│   ├── connection.py         # VectorConnection context manager
│   ├── robot.py              # High-level robot commands
│   └── safety.py             # Emergency stop, signal handlers
│
├── web/                      # Web dashboard
│   ├── server.py             # FastAPI backend (camera WS, telemetry WS, motor API)
│   └── static/
│       ├── index.html        # Dashboard UI
│       ├── style.css         # Dark tech theme
│       └── app.js            # Frontend controller
│
├── tools/
│   └── vector_diagnostics.py # Connectivity diagnostics
│
├── tests/
│   ├── test_connection.py    # Connection verification
│   └── test_robot.py         # Movement sequence test
│
└── main.py                   # Terminal remote control (curses)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Robot SDK | [wirepod-vector-sdk](https://pypi.org/project/wirepod-vector-sdk/) 0.8.1 |
| Local server | [Wire-Pod](https://github.com/kercre123/wire-pod) v1.2.18 |
| Backend | FastAPI + uvicorn |
| Camera stream | WebSocket (base64 JPEG, ~10 FPS) |
| Telemetry | WebSocket (JSON, 2 Hz) |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| Protocol | gRPC over TLS (protobuf) |

## Available Telemetry

| Sensor | Data |
|--------|------|
| Battery | Level, voltage, charging state |
| Proximity | Distance (mm), object detection |
| Pose | X, Y, Z position + heading angle |
| Accelerometer | 3-axis acceleration |
| Gyroscope | 3-axis angular velocity |
| Head | Angle in radians |
| Lift | Height in mm |

## Future Plans

- [ ] OpenCV ArUco marker detection
- [ ] Autonomous navigation with waypoints
- [ ] Nav map visualization
- [ ] Face recognition integration
- [ ] Audio feed streaming
- [ ] Local AI integration (LLM-driven behaviors)
- [ ] Multi-robot support

## Key Resources

- [Wire-Pod](https://github.com/kercre123/wire-pod) — Free local server for Vector
- [wirepod-vector-python-sdk](https://github.com/kercre123/wirepod-vector-python-sdk) — Python SDK fork
- [vector.techshop82.com](https://vector.techshop82.com) — Alternative firmware flashing tool
- [wpsetup.keriganc.com](https://wpsetup.keriganc.com) — Official Wire-Pod setup page
- [Vector SDK docs](https://keriganc.com/sdkdocs) — SDK documentation
- [Vector TRM (Bible)](https://github.com/GooeyChickenman/victor/blob/master/documentation/Vector-TRM.pdf) — Technical reference

## License

MIT
