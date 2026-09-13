/*
 * VectorControl — Anki Vector Robot Controller
 * Copyright (c) 2026 Roberto Calvi — Calvi Tecnologie
 * Email: roberto@calvitecnologie.it
 * License: MIT (see LICENSE file)
 */

(function () {
  "use strict";

  const WS_BASE = `ws://${location.host}`;
  const API_BASE = `http://${location.host}`;

  // DOM refs — Status
  const $connStatus   = document.getElementById("connection-status");
  const $cameraDot    = document.getElementById("camera-dot");
  const $cameraFeed   = document.getElementById("camera-feed");
  const $cameraOvl    = document.getElementById("camera-overlay");
  const $fps          = document.getElementById("fps");
  const $topBatPct    = document.getElementById("topbar-battery-pct");
  const $topBatIcon   = document.getElementById("topbar-battery-icon");

  // DOM refs — Status cards
  const $sBattery     = document.getElementById("s-battery");
  const $sBatteryV    = document.getElementById("s-battery-volts");
  const $sCharger     = document.getElementById("s-charger");
  const $sFirmware    = document.getElementById("s-firmware");
  const $sProximity   = document.getElementById("s-proximity");
  const $sHeadLift    = document.getElementById("s-headlift");
  const $sPose        = document.getElementById("s-pose");
  const $sAccel       = document.getElementById("s-accel");
  const $sGyro        = document.getElementById("s-gyro");
  const $batFill      = document.getElementById("battery-fill");

  // DOM refs — Drive
  const $btnFwd       = document.getElementById("btn-fwd");
  const $btnBack      = document.getElementById("btn-back");
  const $btnLeft      = document.getElementById("btn-left");
  const $btnRight     = document.getElementById("btn-right");
  const $btnStop      = document.getElementById("btn-stop");

  // DOM refs — Head / Lift
  const $btnHeadUp    = document.getElementById("btn-head-up");
  const $btnHeadDown  = document.getElementById("btn-head-down");
  const $btnLiftUp    = document.getElementById("btn-lift-up");
  const $btnLiftDown  = document.getElementById("btn-lift-down");
  const $headInd      = document.getElementById("head-indicator");
  const $liftInd      = document.getElementById("lift-indicator");

  // DOM refs — Speed
  const $speedSlider  = document.getElementById("speed-slider");
  const $speedInfo    = document.getElementById("speed-info");
  const $speedBtns    = document.querySelectorAll(".speed-btn");

  // DOM refs — Actions
  const $btnWake      = document.getElementById("btn-wake");
  const $btnGoHome    = document.getElementById("btn-go-home");
  const $btnOffChgr   = document.getElementById("btn-off-charger");
  const $btnRelease   = document.getElementById("btn-release-control");
  const $btnDockSleep = document.getElementById("btn-dock-sleep");

  // DOM refs — Speech
  const $speechIn     = document.getElementById("speech-input");
  const $speechBtn    = document.getElementById("speech-btn");

  // DOM refs — Events
  const $eventsList   = document.getElementById("events-list");
  const $btnClearLogs = document.getElementById("btn-clear-logs");

  let cameraWs = null;
  let telemetryWs = null;
  let frameCount = 0;
  let lastFpsTime = Date.now();
  let currentSpeedLevel = 1;
  const activeKeys = new Set();

  const SPEED_PRESETS = [
    { drive: 40,  label: "SLOW",   mmps: "40 mm/s" },
    { drive: 80,  label: "MEDIUM", mmps: "80 mm/s" },
    { drive: 130, label: "FAST",   mmps: "130 mm/s" },
    { drive: 180, label: "FAST+",  mmps: "180 mm/s" },
    { drive: 220, label: "MAX",    mmps: "220 mm/s" },
  ];

  // -----------------------------------------------------------------------
  // API helper
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
  // Events log
  // -----------------------------------------------------------------------
  function addEvent(text, type) {
    type = type || "info";
    const now = new Date();
    const ts = now.toTimeString().slice(0, 8);
    const item = document.createElement("div");
    item.className = "event-item";
    item.innerHTML =
      `<span class="event-time">${ts}</span>` +
      `<span class="event-dot dot-${type}"></span>` +
      `<span>${text}</span>`;
    $eventsList.prepend(item);
    while ($eventsList.children.length > 50) {
      $eventsList.removeChild($eventsList.lastChild);
    }
  }

  $btnClearLogs.addEventListener("click", () => {
    $eventsList.innerHTML = "";
    addEvent("Logs cleared", "info");
  });

  // -----------------------------------------------------------------------
  // Connection status polling
  // -----------------------------------------------------------------------
  let lastState = "";

  async function checkStatus() {
    try {
      const r = await fetch(`${API_BASE}/api/status`);
      const d = await r.json();
      if (d.connected) {
        $connStatus.textContent = "ONLINE";
        $connStatus.className = "status-badge online";
        if (d.firmware) $sFirmware.textContent = d.firmware;
        if (d.is_on_charger !== undefined) $sCharger.textContent = d.is_on_charger ? "Yes" : "No";

        const pct = Math.round((d.battery_level / 3) * 100);
        $sBattery.textContent = pct + "%";
        $sBatteryV.textContent = d.battery_volts + " V";
        $topBatPct.textContent = pct + "%";
        $batFill.style.width = pct + "%";
        if (pct < 25) { $batFill.style.background = "var(--danger)"; }
        else if (pct < 50) { $batFill.style.background = "var(--warning)"; }
        else { $batFill.style.background = "var(--accent)"; }

        if (d.is_charging) $topBatIcon.textContent = "\u26A1";
        else $topBatIcon.textContent = "\uD83D\uDD0B";
      } else {
        $connStatus.textContent = "OFFLINE";
        $connStatus.className = "status-badge";
      }

      const state = d.state || "disconnected";
      updateWakeState(state);

      if (state !== lastState) {
        lastState = state;
        addEvent("State: " + state, state === "awake" ? "success" : "warning");
      }
    } catch {
      $connStatus.textContent = "OFFLINE";
      $connStatus.className = "status-badge";
    }
  }

  function updateWakeState(state) {
    if ($btnWake) {
      if (state === "waking") {
        $btnWake.disabled = true;
        $btnWake.classList.add("waking");
        $btnWake.querySelector(".action-label").textContent = "WAKING UP...";
      } else {
        $btnWake.disabled = false;
        $btnWake.classList.remove("waking");
        $btnWake.querySelector(".action-label").textContent = "WAKE UP VECTOR";
      }
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
      $cameraDot.classList.add("connected");
      addEvent("Camera stream started", "success");
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
      $cameraFeed.style.display = "none";
      $cameraDot.classList.remove("connected");
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
      try { updateTelemetry(JSON.parse(ev.data)); } catch {}
    };

    telemetryWs.onclose = () => setTimeout(connectTelemetry, 3000);
    telemetryWs.onerror = () => telemetryWs.close();
  }

  function updateTelemetry(d) {
    if (d.battery) {
      const pct = Math.round((d.battery.level / 3) * 100);
      $sBattery.textContent = pct + "%";
      $sBatteryV.textContent = d.battery.volts + " V";
      $topBatPct.textContent = pct + "%";
      $batFill.style.width = pct + "%";
      if (pct < 25) $batFill.style.background = "var(--danger)";
      else if (pct < 50) $batFill.style.background = "var(--warning)";
      else $batFill.style.background = "var(--accent)";
      $sCharger.textContent = d.battery.on_charger ? "Yes" : "No";
      $topBatIcon.textContent = d.battery.charging ? "\u26A1" : "\uD83D\uDD0B";
    }

    if (d.proximity) {
      $sProximity.textContent = d.proximity.distance_mm + " mm";
    }

    if (d.pose) {
      $sPose.textContent = `X:${d.pose.x} Y:${d.pose.y} A:${d.pose.angle_deg}\u00B0`;
    }

    if (d.head_angle_rad !== undefined) {
      const headDeg = (d.head_angle_rad * 180 / Math.PI).toFixed(1);
      const liftMm = d.lift_height_mm !== undefined ? d.lift_height_mm.toFixed(0) : "?";
      $sHeadLift.textContent = `H:${headDeg}\u00B0 L:${liftMm}mm`;
      if ($headInd) $headInd.textContent = headDeg + "\u00B0";
      if ($liftInd) $liftInd.textContent = liftMm + " mm";
    }

    if (d.accel) {
      $sAccel.textContent = `${d.accel.x} ${d.accel.y} ${d.accel.z}`;
    }

    if (d.gyro) {
      $sGyro.textContent = `${d.gyro.x} ${d.gyro.y} ${d.gyro.z}`;
    }
  }

  // -----------------------------------------------------------------------
  // Control tabs
  // -----------------------------------------------------------------------
  document.querySelectorAll(".ctrl-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".ctrl-tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".ctrl-tab-content").forEach((c) => c.classList.remove("active"));
      tab.classList.add("active");
      const target = document.getElementById("tab-" + tab.dataset.tab);
      if (target) target.classList.add("active");
    });
  });

  // -----------------------------------------------------------------------
  // Motor control — hold to move
  // -----------------------------------------------------------------------
  function setupHoldButton(btn, startFn, stopFn) {
    if (!btn) return;
    let holding = false;
    const start = (e) => {
      e.preventDefault();
      if (!holding) { holding = true; btn.classList.add("active"); startFn(); }
    };
    const stop = () => {
      if (holding) { holding = false; btn.classList.remove("active"); stopFn(); }
    };
    btn.addEventListener("mousedown", start);
    btn.addEventListener("mouseup", stop);
    btn.addEventListener("mouseleave", stop);
    btn.addEventListener("touchstart", start, { passive: false });
    btn.addEventListener("touchend", stop);
    btn.addEventListener("touchcancel", stop);
  }

  setupHoldButton($btnFwd,   () => post("/api/drive", { action: "forward" }),  () => post("/api/drive", { action: "stop" }));
  setupHoldButton($btnBack,  () => post("/api/drive", { action: "backward" }), () => post("/api/drive", { action: "stop" }));
  setupHoldButton($btnLeft,  () => post("/api/drive", { action: "left" }),     () => post("/api/drive", { action: "stop" }));
  setupHoldButton($btnRight, () => post("/api/drive", { action: "right" }),    () => post("/api/drive", { action: "stop" }));
  if ($btnStop) $btnStop.addEventListener("click", () => post("/api/stop"));

  setupHoldButton($btnHeadUp,   () => post("/api/head", { direction: "up" }),   () => post("/api/head/stop"));
  setupHoldButton($btnHeadDown, () => post("/api/head", { direction: "down" }), () => post("/api/head/stop"));
  setupHoldButton($btnLiftUp,   () => post("/api/lift", { direction: "up" }),   () => post("/api/lift/stop"));
  setupHoldButton($btnLiftDown, () => post("/api/lift", { direction: "down" }), () => post("/api/lift/stop"));

  // -----------------------------------------------------------------------
  // Keyboard controls
  // -----------------------------------------------------------------------
  const KEY_MAP = {
    w:          { type: "drive", action: "forward",  btn: $btnFwd },
    s:          { type: "drive", action: "backward", btn: $btnBack },
    a:          { type: "drive", action: "left",     btn: $btnLeft },
    d:          { type: "drive", action: "right",    btn: $btnRight },
    arrowup:    { type: "head",  action: "up",       btn: $btnHeadUp },
    arrowdown:  { type: "head",  action: "down",     btn: $btnHeadDown },
    r:          { type: "lift",  action: "up",       btn: $btnLiftUp },
    f:          { type: "lift",  action: "down",     btn: $btnLiftDown },
    " ":        { type: "stop",  action: "stop",     btn: $btnStop },
  };

  document.addEventListener("keydown", (e) => {
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

    if (m.type === "drive") post("/api/drive", { action: m.action });
    else if (m.type === "head") post("/api/head", { direction: m.action });
    else if (m.type === "lift") post("/api/lift", { direction: m.action });
    else if (m.type === "stop") post("/api/stop");
  });

  document.addEventListener("keyup", (e) => {
    if (document.activeElement === $speechIn) return;
    const key = e.key.toLowerCase();
    if (!(key in KEY_MAP)) return;
    e.preventDefault();
    activeKeys.delete(key);

    const m = KEY_MAP[key];
    if (m.btn) m.btn.classList.remove("active");

    if (m.type === "drive") {
      if (!["w", "a", "s", "d"].some((k) => activeKeys.has(k))) {
        post("/api/drive", { action: "stop" });
      }
    } else if (m.type === "head") {
      post("/api/head/stop");
    } else if (m.type === "lift") {
      post("/api/lift/stop");
    }
  });

  // -----------------------------------------------------------------------
  // Speed control
  // -----------------------------------------------------------------------
  function updateSpeedUI(level) {
    currentSpeedLevel = level;
    $speedSlider.value = level;
    $speedInfo.textContent = SPEED_PRESETS[level].mmps;
    $speedBtns.forEach((btn) => {
      const bl = parseInt(btn.dataset.level);
      btn.classList.toggle("active", bl === level);
    });
  }

  function setSpeed(level) {
    level = Math.max(0, Math.min(level, 4));
    post("/api/speed", { level });
    updateSpeedUI(level);
  }

  $speedSlider.addEventListener("input", () => setSpeed(parseInt($speedSlider.value)));
  $speedBtns.forEach((btn) => {
    btn.addEventListener("click", () => setSpeed(parseInt(btn.dataset.level)));
  });

  updateSpeedUI(1);

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------
  $btnWake.addEventListener("click", async () => {
    const r = await post("/api/wake");
    if (r) {
      updateWakeState(r.state || "waking");
      addEvent("Wake sequence started", "warning");
    }
  });

  $btnGoHome.addEventListener("click", () => {
    post("/api/go_home");
    addEvent("Go Home command sent", "info");
  });

  $btnOffChgr.addEventListener("click", () => {
    post("/api/drive_off_charger");
    addEvent("Off Charger command sent", "info");
  });

  $btnRelease.addEventListener("click", async () => {
    const r = await post("/api/release_control");
    if (r) addEvent("Control released", "warning");
  });

  $btnDockSleep.addEventListener("click", () => {
    post("/api/go_home");
    addEvent("Dock & Sleep command sent", "info");
  });

  // -----------------------------------------------------------------------
  // Quick Actions
  // -----------------------------------------------------------------------
  document.querySelectorAll(".quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.quick;
      post("/api/quick_action", { action });
      addEvent("Quick action: " + action.replace(/_/g, " "), "info");
    });
  });

  // -----------------------------------------------------------------------
  // Speech
  // -----------------------------------------------------------------------
  function sayText(text) {
    if (!text) return;
    post("/api/say", { text });
    addEvent('Say: "' + text + '"', "info");
  }

  $speechBtn.addEventListener("click", () => {
    const text = $speechIn.value.trim();
    if (text) { sayText(text); $speechIn.value = ""; }
  });

  $speechIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $speechBtn.click(); }
  });

  document.querySelectorAll(".phrase-btn").forEach((btn) => {
    btn.addEventListener("click", () => sayText(btn.dataset.phrase));
  });

  // -----------------------------------------------------------------------
  // Screenshot
  // -----------------------------------------------------------------------
  const $btnScreenshot = document.getElementById("btn-screenshot");
  if ($btnScreenshot) {
    $btnScreenshot.addEventListener("click", () => {
      if ($cameraFeed.src) {
        const a = document.createElement("a");
        a.href = $cameraFeed.src;
        a.download = "vector-screenshot-" + Date.now() + ".jpg";
        a.click();
        addEvent("Screenshot saved", "success");
      }
    });
  }

  // -----------------------------------------------------------------------
  // Fullscreen
  // -----------------------------------------------------------------------
  const $btnFullscreen = document.getElementById("btn-fullscreen");
  if ($btnFullscreen) {
    $btnFullscreen.addEventListener("click", () => {
      const container = document.querySelector(".camera-container");
      if (container.requestFullscreen) container.requestFullscreen();
      else if (container.webkitRequestFullscreen) container.webkitRequestFullscreen();
    });
  }

  // -----------------------------------------------------------------------
  // Navigation (top + bottom)
  // -----------------------------------------------------------------------
  function setupNav(selector) {
    document.querySelectorAll(selector).forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(selector).forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        document.querySelectorAll(".topbar-nav .nav-tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".bottom-nav .bnav-btn").forEach((t) => t.classList.remove("active"));

        const section = btn.dataset.section;
        document.querySelectorAll(`[data-section="${section}"]`).forEach((el) => el.classList.add("active"));

        const target = document.getElementById("section-" + section);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  setupNav(".topbar-nav .nav-tab");
  setupNav(".bottom-nav .bnav-btn");

  // -----------------------------------------------------------------------
  // Init
  // -----------------------------------------------------------------------
  checkStatus();
  setInterval(checkStatus, 5000);
  connectCamera();
  connectTelemetry();
  addEvent("Dashboard loaded", "info");

})();
