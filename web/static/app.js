/* VectorControl Dashboard — Frontend Controller */

(function () {
  "use strict";

  // -----------------------------------------------------------------------
  // DOM refs
  // -----------------------------------------------------------------------
  const $status     = document.getElementById("connection-status");
  const $firmware   = document.getElementById("firmware");
  const $cameraFeed = document.getElementById("camera-feed");
  const $cameraOvl  = document.getElementById("camera-overlay");
  const $fps        = document.getElementById("fps");
  const $speechIn   = document.getElementById("speech-input");
  const $speechBtn  = document.getElementById("speech-btn");

  // Telemetry
  const $tBattery   = document.getElementById("t-battery");
  const $tProximity = document.getElementById("t-proximity");
  const $tPose      = document.getElementById("t-pose");
  const $tHeadLift  = document.getElementById("t-headlift");
  const $tAccel     = document.getElementById("t-accel");
  const $tGyro      = document.getElementById("t-gyro");
  const $batFill    = document.getElementById("battery-fill");

  // Drive buttons
  const $btnFwd   = document.getElementById("btn-fwd");
  const $btnBack  = document.getElementById("btn-back");
  const $btnLeft  = document.getElementById("btn-left");
  const $btnRight = document.getElementById("btn-right");
  const $btnStop  = document.getElementById("btn-stop");

  // Head / Lift buttons
  const $btnHeadUp   = document.getElementById("btn-head-up");
  const $btnHeadDown = document.getElementById("btn-head-down");
  const $btnLiftUp   = document.getElementById("btn-lift-up");
  const $btnLiftDown = document.getElementById("btn-lift-down");

  const $speedSlider = document.getElementById("speed-slider");
  const $speedInfo   = document.getElementById("speed-info");
  const $speedDown   = document.getElementById("speed-down");
  const $speedUp     = document.getElementById("speed-up");
  const $speedTags   = document.querySelectorAll(".speed-tag");

  const WS_BASE = `ws://${location.host}`;
  const API_BASE = `http://${location.host}`;
  let cameraWs = null;
  let telemetryWs = null;
  let frameCount = 0;
  let lastFpsTime = Date.now();
  let currentSpeedLevel = 1;
  const SPEED_PRESETS = [
    { drive: 40,  label: "CAUTO" },
    { drive: 80,  label: "LENTO" },
    { drive: 130, label: "MEDIO" },
    { drive: 180, label: "VELOCE" },
    { drive: 220, label: "MAX" },
  ];

  const activeKeys = new Set();

  // -----------------------------------------------------------------------
  // API helpers
  // -----------------------------------------------------------------------
  async function post(path, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const url = qs ? `${API_BASE}${path}?${qs}` : `${API_BASE}${path}`;
    try {
      const r = await fetch(url, { method: "POST" });
      return await r.json();
    } catch (e) {
      console.error("API error:", path, e);
      return null;
    }
  }

  // -----------------------------------------------------------------------
  // Connection status
  // -----------------------------------------------------------------------
  async function checkStatus() {
    try {
      const r = await fetch(`${API_BASE}/api/status`);
      const d = await r.json();
      if (d.connected) {
        $status.textContent = "ONLINE";
        $status.className = "status-badge online";
        $firmware.textContent = `FW ${d.firmware || "?"}`;
      } else {
        $status.textContent = "OFFLINE";
        $status.className = "status-badge offline";
      }
      updateWakeState(d.state || "disconnected");
    } catch {
      $status.textContent = "OFFLINE";
      $status.className = "status-badge offline";
      updateWakeState("disconnected");
    }
  }

  // -----------------------------------------------------------------------
  // Camera WebSocket
  // -----------------------------------------------------------------------
  function connectCamera() {
    if (cameraWs && cameraWs.readyState <= 1) return;
    cameraWs = new WebSocket(`${WS_BASE}/ws/camera`);

    cameraWs.onopen = () => {
      $cameraOvl.classList.add("hidden");
      $cameraFeed.style.display = "block";
    };

    cameraWs.onmessage = (ev) => {
      $cameraFeed.src = "data:image/jpeg;base64," + ev.data;
      frameCount++;
      const now = Date.now();
      if (now - lastFpsTime >= 1000) {
        $fps.textContent = frameCount + " FPS";
        frameCount = 0;
        lastFpsTime = now;
      }
    };

    cameraWs.onclose = () => {
      $cameraOvl.classList.remove("hidden");
      $cameraOvl.querySelector("span").textContent = "Camera disconnected — reconnecting…";
      $cameraFeed.style.display = "none";
      setTimeout(connectCamera, 2000);
    };

    cameraWs.onerror = () => cameraWs.close();
  }

  // -----------------------------------------------------------------------
  // Telemetry WebSocket
  // -----------------------------------------------------------------------
  function connectTelemetry() {
    if (telemetryWs && telemetryWs.readyState <= 1) return;
    telemetryWs = new WebSocket(`${WS_BASE}/ws/telemetry`);

    telemetryWs.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        updateTelemetry(d);
      } catch { /* ignore parse errors */ }
    };

    telemetryWs.onclose = () => setTimeout(connectTelemetry, 3000);
    telemetryWs.onerror = () => telemetryWs.close();
  }

  function updateTelemetry(d) {
    // Battery
    if (d.battery) {
      const lvl = d.battery.level;
      const pct = Math.round((lvl / 3) * 100);
      const icon = d.battery.charging ? " &#9889;" : "";
      $tBattery.innerHTML = `${d.battery.volts}V${icon}`;
      $batFill.style.width = pct + "%";
      if (pct < 25) $batFill.style.background = "#ef4444";
      else if (pct < 50) $batFill.style.background = "#f59e0b";
      else $batFill.style.background = "#00e5a0";
    }

    // Proximity
    if (d.proximity) {
      const dist = d.proximity.distance_mm;
      const obj = d.proximity.found_object ? " OBJ" : "";
      $tProximity.textContent = `${dist} mm${obj}`;
    }

    // Pose
    if (d.pose) {
      $tPose.textContent = `X:${d.pose.x} Y:${d.pose.y} Z:${d.pose.z} A:${d.pose.angle_deg}\u00B0`;
    }

    // Head / Lift
    if (d.head_angle_rad !== undefined) {
      const headDeg = (d.head_angle_rad * 180 / Math.PI).toFixed(1);
      const liftMm = d.lift_height_mm !== undefined ? d.lift_height_mm.toFixed(0) : "?";
      $tHeadLift.textContent = `Head: ${headDeg}\u00B0  Lift: ${liftMm}mm`;
    }

    // Accel
    if (d.accel) {
      $tAccel.textContent = `X:${d.accel.x} Y:${d.accel.y} Z:${d.accel.z}`;
    }

    // Gyro
    if (d.gyro) {
      $tGyro.textContent = `X:${d.gyro.x} Y:${d.gyro.y} Z:${d.gyro.z}`;
    }
  }

  // -----------------------------------------------------------------------
  // Motor control — keyboard
  // -----------------------------------------------------------------------
  const KEY_MAP = {
    w:          { type: "drive",  action: "forward",  btn: $btnFwd },
    s:          { type: "drive",  action: "backward", btn: $btnBack },
    a:          { type: "drive",  action: "left",     btn: $btnLeft },
    d:          { type: "drive",  action: "right",    btn: $btnRight },
    arrowup:    { type: "head",   action: "up",       btn: $btnHeadUp },
    arrowdown:  { type: "head",   action: "down",     btn: $btnHeadDown },
    r:          { type: "lift",   action: "up",       btn: $btnLiftUp },
    f:          { type: "lift",   action: "down",     btn: $btnLiftDown },
    " ":        { type: "stop",   action: "stop",     btn: $btnStop },
  };

  document.addEventListener("keydown", (e) => {
    // Don't capture when typing in the speech input
    if (document.activeElement === $speechIn) return;

    const key = e.key.toLowerCase();

    if (key >= "1" && key <= "5") {
      e.preventDefault();
      setSpeed(parseInt(key) - 1);
      return;
    }

    if (!(key in KEY_MAP)) return;
    e.preventDefault();

    if (activeKeys.has(key)) return;
    activeKeys.add(key);

    const m = KEY_MAP[key];
    if (m.btn) m.btn.classList.add("active");

    if (m.type === "drive") {
      post("/api/drive", { action: m.action });
    } else if (m.type === "head") {
      post("/api/head", { direction: m.action });
    } else if (m.type === "lift") {
      post("/api/lift", { direction: m.action });
    } else if (m.type === "stop") {
      post("/api/stop");
    }
  });

  document.addEventListener("keyup", (e) => {
    if (document.activeElement === $speechIn) return;

    const key = e.key.toLowerCase();
    if (!(key in KEY_MAP)) return;
    e.preventDefault();

    activeKeys.delete(key);

    const m = KEY_MAP[key];
    if (m.btn) m.btn.classList.remove("active");

    // Stop the relevant motor group on key release
    if (m.type === "drive") {
      // Only stop if no other drive key is held
      const driveKeys = ["w", "a", "s", "d"];
      if (!driveKeys.some(k => activeKeys.has(k))) {
        post("/api/drive", { action: "stop" });
      }
    } else if (m.type === "head") {
      post("/api/head/stop");
    } else if (m.type === "lift") {
      post("/api/lift/stop");
    }
  });

  // -----------------------------------------------------------------------
  // Motor control — click buttons (toggle: click to start, click again or STOP to stop)
  // -----------------------------------------------------------------------
  let activeDrive = null;

  function stopAllDrive() {
    activeDrive = null;
    [$btnFwd, $btnBack, $btnLeft, $btnRight].forEach(b => b.classList.remove("active"));
    post("/api/drive", { action: "stop" });
  }

  function toggleDrive(btn, action) {
    if (activeDrive === action) {
      stopAllDrive();
    } else {
      stopAllDrive();
      activeDrive = action;
      btn.classList.add("active");
      post("/api/drive", { action });
    }
  }

  $btnFwd.addEventListener("click",   () => toggleDrive($btnFwd, "forward"));
  $btnBack.addEventListener("click",  () => toggleDrive($btnBack, "backward"));
  $btnLeft.addEventListener("click",  () => toggleDrive($btnLeft, "left"));
  $btnRight.addEventListener("click", () => toggleDrive($btnRight, "right"));
  $btnStop.addEventListener("click",  () => { stopAllDrive(); post("/api/stop"); });

  // Head — click to move for 0.5s
  $btnHeadUp.addEventListener("click", () => {
    post("/api/head", { direction: "up" });
    setTimeout(() => post("/api/head/stop"), 500);
  });
  $btnHeadDown.addEventListener("click", () => {
    post("/api/head", { direction: "down" });
    setTimeout(() => post("/api/head/stop"), 500);
  });

  // Lift — click to move for 0.5s
  $btnLiftUp.addEventListener("click", () => {
    post("/api/lift", { direction: "up" });
    setTimeout(() => post("/api/lift/stop"), 500);
  });
  $btnLiftDown.addEventListener("click", () => {
    post("/api/lift", { direction: "down" });
    setTimeout(() => post("/api/lift/stop"), 500);
  });

  // -----------------------------------------------------------------------
  // Speech
  // -----------------------------------------------------------------------
  $speechBtn.addEventListener("click", () => {
    const text = $speechIn.value.trim();
    if (!text) return;
    post("/api/say", { text });
    $speechIn.value = "";
  });

  $speechIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      $speechBtn.click();
    }
  });

  const $btnGoHome         = document.getElementById("btn-go-home");
  const $btnOffCharger     = document.getElementById("btn-off-charger");
  const $btnWake           = document.getElementById("btn-wake");
  const $btnReleaseControl = document.getElementById("btn-release-control");
  const $wakeState         = document.getElementById("wake-state");

  $btnGoHome.addEventListener("click", () => post("/api/go_home"));
  $btnOffCharger.addEventListener("click", () => post("/api/drive_off_charger"));

  $btnWake.addEventListener("click", async () => {
    const r = await post("/api/wake");
    if (r) updateWakeState(r.state || "waking");
  });

  $btnReleaseControl.addEventListener("click", async () => {
    const r = await post("/api/release_control");
    if (r) updateWakeState(r.state || "connected");
  });

  const WAKE_STATE_DISPLAY = {
    disconnected: { text: "DISCONNECTED", cls: "offline"  },
    connecting:   { text: "CONNECTING…",  cls: "warning"  },
    connected:    { text: "CONNECTED",    cls: "warning"  },
    waking:       { text: "WAKING…",      cls: "warning"  },
    awake:        { text: "AWAKE",        cls: "online"   },
    error:        { text: "ERROR",        cls: "offline"  },
  };

  function updateWakeState(state) {
    const s = WAKE_STATE_DISPLAY[state] || { text: state.toUpperCase(), cls: "offline" };
    if ($wakeState) {
      $wakeState.textContent = s.text;
      $wakeState.className = "status-badge " + s.cls;
    }
    if ($btnWake) {
      $btnWake.disabled = (state === "waking");
      $btnWake.textContent = state === "waking" ? "\u26A1 WAKING\u2026" : "\u26A1 WAKE UP VECTOR";
    }
  }

  // -----------------------------------------------------------------------
  // Speed control
  // -----------------------------------------------------------------------
  function updateSpeedUI(level) {
    currentSpeedLevel = level;
    $speedSlider.value = level;
    $speedInfo.textContent = SPEED_PRESETS[level].drive + " mm/s — " + SPEED_PRESETS[level].label;
    $speedTags.forEach(tag => {
      tag.classList.toggle("active", parseInt(tag.dataset.level) === level);
    });
  }

  function setSpeed(level) {
    level = Math.max(0, Math.min(level, 4));
    post("/api/speed", { level });
    updateSpeedUI(level);
  }

  $speedSlider.addEventListener("input", () => setSpeed(parseInt($speedSlider.value)));
  $speedDown.addEventListener("click", () => setSpeed(currentSpeedLevel - 1));
  $speedUp.addEventListener("click", () => setSpeed(currentSpeedLevel + 1));
  $speedTags.forEach(tag => {
    tag.addEventListener("click", () => setSpeed(parseInt(tag.dataset.level)));
  });

  updateSpeedUI(1);

  // -----------------------------------------------------------------------
  // Init
  // -----------------------------------------------------------------------
  checkStatus();
  setInterval(checkStatus, 5000);
  connectCamera();
  connectTelemetry();

})();
