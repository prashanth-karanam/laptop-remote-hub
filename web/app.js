/* Laptop Remote Hub Client-side Engine */

let ws = null;
let currentPin = "";
let isConnected = false;
let isDragLocked = false;
let screenStreamActive = false;
let screenTimer = null;
let currentPath = "C:\\Users\\Praashu";

// Query param auto-fill for PIN and target backend
const urlParams = new URLSearchParams(window.location.search);
const pinFromUrl = urlParams.get("pin");
const targetFromUrl = urlParams.get("target");

let backendBaseUrl = targetFromUrl || localStorage.getItem("remote_hub_target") || "";

function setBackendTarget(url) {
  if (url) {
    backendBaseUrl = url.replace(/\/+$/, '');
    localStorage.setItem("remote_hub_target", backendBaseUrl);
    console.log("[RemoteHub] Backend target set to:", backendBaseUrl);
  }
}

if (targetFromUrl) {
  setBackendTarget(targetFromUrl);
}

function getApiUrl(endpoint) {
  if (backendBaseUrl) {
    const base = backendBaseUrl.replace(/\/+$/, '');
    const path = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
    return `${base}${path}`;
  }
  return endpoint;
}

function getWsUrl(endpoint) {
  const path = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
  if (backendBaseUrl) {
    try {
      const u = new URL(backendBaseUrl);
      const wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${wsProto}//${u.host}${path}`;
    } catch(e) {}
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}

// DOM Elements
const authModal = document.getElementById("auth-modal");
const appContainer = document.getElementById("app-container");
const pinInput = document.getElementById("pin-input");
const btnLogin = document.getElementById("btn-login");
const authError = document.getElementById("auth-error");

// Initialize on Load
window.addEventListener("DOMContentLoaded", () => {
  setupNavigation();
  setupTouchpad();
  setupScreenStream();
  setupDesktopInputPassThrough();
  setupLiveTyping();
  setupTerminal();
  setupFiles();
  setupShortcuts();
  setupClipboard();
  setupAppSearch();

  // Mode Auto-detection: Second Screen / Laptop Mode for laptops/desktops, Mobile Touchpad for phones
  const savedMode = localStorage.getItem("remote_hub_ui_mode");
  const isLargeScreen = window.innerWidth >= 900 && (!('ontouchstart' in window) || navigator.maxTouchPoints <= 1);
  const initialMode = savedMode || (isLargeScreen ? "desktop" : "mobile");
  setUIMode(initialMode, true);

  if (pinFromUrl) {
    pinInput.value = pinFromUrl;
    attemptConnect(pinFromUrl);
  }

  btnLogin.addEventListener("click", () => {
    const pin = pinInput.value.trim();
    if (pin) {
      attemptConnect(pin);
    }
  });

  pinInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      btnLogin.click();
    }
  });
});

// ================= WEBSOCKET & AUTH =================

function attemptConnect(pin) {
  currentPin = pin;
  authError.textContent = "Connecting to laptop...";

  // Quick HTTP Auth check for instant UI unlock
  fetch(getApiUrl(`/api/status?pin=${pin}`))
    .then(res => {
      if (res.ok) {
        isConnected = true;
        authModal.classList.add("hidden");
        appContainer.classList.remove("hidden");
        authError.textContent = "";
        if (currentUIMode === "desktop") {
          startScreenStream();
        }
        return res.json();
      } else {
        authError.textContent = "Invalid PIN.";
      }
    })
    .then(data => {
      if (data) updateTelemetryUI(data);
    })
    .catch(err => {
      console.warn("HTTP Auth fallback warning:", err);
    });

  const wsUrl = getWsUrl("/ws");

  try {
    if (ws) {
      try { ws.close(); } catch(e) {}
    }
    ws = new WebSocket(wsUrl);

    let pingTimer = null;

    ws.onopen = () => {
      console.log("WebSocket connected. Authenticating...");
      ws.send(JSON.stringify({ type: "auth", pin: pin }));
      document.getElementById("srm-status").innerHTML = `<span class="dot green"></span><span class="label">Connected</span>`;
      
      // Start 15s heartbeat to prevent Cloudflare 100s idle WebSocket timeout
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 15000);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "pong") {
        // Heartbeat acknowledged
        return;
      }
      handleWsMessage(data);
    };

    ws.onerror = (err) => {
      console.warn("WS error:", err);
    };

    ws.onclose = () => {
      if (pingTimer) clearInterval(pingTimer);
      isConnected = false;
      document.getElementById("srm-status").innerHTML = `<span class="dot red"></span><span class="label">Reconnecting...</span>`;
      // Instant retry on drop
      setTimeout(() => {
        if (currentPin) attemptConnect(currentPin);
      }, 1500);
    };
  } catch (err) {
    authError.textContent = "Connection error: " + err.message;
  }
}

// Handle Mobile Wake-up / Tab Switch Auto-Reconnect
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    console.log("[Mobile Wakeup] Screen turned ON / Tab Focused. Reconnecting...");
    if (currentPin) {
      attemptConnect(currentPin);
    }
    const screenPanel = document.getElementById("view-screen");
    if (screenPanel && screenPanel.classList.contains("active")) {
      startScreenStream();
    }
  } else {
    stopScreenStream();
  }
});

window.addEventListener("focus", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    if (currentPin) attemptConnect(currentPin);
  }
});

window.addEventListener("online", () => {
  console.log("[Network Online] Reconnecting...");
  if (currentPin) attemptConnect(currentPin);
});

// Periodic Watchdog Check
setInterval(() => {
  if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
    if (currentPin && document.visibilityState === "visible") {
      attemptConnect(currentPin);
    }
  }
}, 4000);

function handleWsMessage(msg) {
  if (msg.type === "auth_ok") {
    isConnected = true;
    authModal.classList.add("hidden");
    appContainer.classList.remove("hidden");
    authError.textContent = "";

    if (currentUIMode === "desktop") {
      startScreenStream();
    }

    // Start background telemetry polling
    pollTelemetry();
  } else if (msg.type === "auth_fail") {
    authError.textContent = "Invalid PIN. Please try again.";
  } else if (msg.type === "terminal_output") {
    appendTerminalOutput(msg.text, msg.stream);
  } else if (msg.type === "terminal_done") {
    appendTerminalOutput(`\n[Process exited with code ${msg.exit_code}]\n`, "info");
  } else if (msg.type === "clipboard_data") {
    const clipInput = document.getElementById("clipboard-input");
    if (clipInput) clipInput.value = msg.text || "";
    if (navigator.clipboard && msg.text) {
      navigator.clipboard.writeText(msg.text).catch(e => {});
    }
    alert("Copied text from PC:\n\n" + (msg.text ? msg.text.substring(0, 100) : "(Empty)"));
  } else if (msg.type === "clipboard_set_ok") {
    alert("Text sent to laptop clipboard!");
  } else if (msg.type === "stats") {
    updateTelemetryUI(msg.data);
  }
}

function sendWs(data) {
  if (typeof boostScreenFps === "function") boostScreenFps();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

// ================= TELEMETRY POLLING =================

async function pollTelemetry() {
  if (!isConnected) return;
  try {
    const res = await fetch(getApiUrl(`/api/status?pin=${currentPin}`));
    if (res.ok) {
      const data = await res.json();
      updateTelemetryUI(data);
    }
  } catch (e) {
    console.error("Telemetry fetch error:", e);
  }
}

function updateTelemetryUI(data) {
  if (!data) return;
  
  // CPU & RAM
  document.getElementById("cpu-val").textContent = `${data.cpu_percent}%`;
  
  // Battery
  if (data.battery) {
    const icon = data.battery.power_plugged ? "fa-bolt" : "fa-battery-half";
    document.getElementById("bat-indicator").innerHTML = `<i class="fa-solid ${icon}"></i> <span id="bat-val">${data.battery.percent}%</span>`;
  }

  // SRM Wi-Fi Sentinel Status
  const srm = data.srm_wifi;
  const srmStatusEl = document.getElementById("srm-status");
  if (srm && srm.connected) {
    srmStatusEl.innerHTML = `<span class="dot green"></span><span class="label">${srm.ssid || 'SRMIST'}: ${srm.latency_ms}ms</span>`;
  } else {
    srmStatusEl.innerHTML = `<span class="dot red"></span><span class="label">Reconnecting...</span>`;
  }
}

// ================= NAVIGATION =================

function setupNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  const panels = document.querySelectorAll(".view-panel");

  navItems.forEach((btn) => {
    btn.addEventListener("click", () => {
      navItems.forEach((b) => b.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-target");
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }

      // If screen view activated, start live screen feed
      if (targetId === "view-screen") {
        startScreenStream();
      } else {
        stopScreenStream();
      }

      // If files view activated, refresh list
      if (targetId === "view-files") {
        loadDirectory(currentPath);
      }
    });
  });
}

// ================= LIVE KEYBOARD & TYPING =================

function setupLiveTyping() {
  const liveBox = document.getElementById("live-typing-box");
  let lastVal = "";

  liveBox.addEventListener("input", (e) => {
    const currentVal = liveBox.value;
    if (e.inputType === "deleteContentBackward") {
      sendKeyPress("backspace");
    } else if (currentVal.length > 0) {
      sendWs({ type: "type_text", text: currentVal, mode: "paste" });
    }
    // Clear box so typing can continue indefinitely
    liveBox.value = "";
    lastVal = "";
  });

  liveBox.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendKeyPress("enter");
      liveBox.value = "";
    } else if (e.key === "Backspace" && liveBox.value === "") {
      sendKeyPress("backspace");
    } else if (e.key === "Tab") {
      e.preventDefault();
      sendKeyPress("tab");
    }
  });

  // Quick action buttons
  document.getElementById("btn-quick-esc").addEventListener("click", () => sendKeyPress("esc"));
  document.getElementById("btn-quick-tab").addEventListener("click", () => sendKeyPress("tab"));
  document.getElementById("btn-quick-bs").addEventListener("click", () => sendKeyPress("backspace"));
  document.getElementById("btn-quick-enter").addEventListener("click", () => sendKeyPress("enter"));
}

let mouseSpeed = 1.4;
let gyroActive = false;
let lastGyroAlpha = null, lastGyroBeta = null, lastGyroGamma = null;

// ================= TOUCHPAD GESTURES & MOUSE CONTROLS =================

function setupTouchpad() {
  const surface = document.getElementById("touchpad-surface");
  const scrollStrip = document.getElementById("scroll-strip");
  
  let startX = 0, startY = 0;
  let lastX = 0, lastY = 0;
  let startTime = 0;
  let isMoving = false;
  let touchCount = 0;

  // Speed Presets
  document.querySelectorAll(".speed-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      mouseSpeed = parseFloat(btn.getAttribute("data-speed")) || 1.4;
    });
  });

  // Air Mouse / Gyro Toggle
  const btnGyro = document.getElementById("btn-toggle-gyro");
  btnGyro.addEventListener("click", async () => {
    if (!gyroActive) {
      if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
        try {
          const perm = await DeviceOrientationEvent.requestPermission();
          if (perm !== 'granted') {
            alert("Gyroscope permission denied.");
            return;
          }
        } catch (e) {
          console.warn("Gyro permission error:", e);
        }
      }
      gyroActive = true;
      btnGyro.classList.add("active");
      window.addEventListener("deviceorientation", handleGyroOrientation);
      if (navigator.vibrate) navigator.vibrate(50);
    } else {
      gyroActive = false;
      btnGyro.classList.remove("active");
      window.removeEventListener("deviceorientation", handleGyroOrientation);
      lastGyroGamma = null;
      lastGyroBeta = null;
    }
  });

  // Touchpad Surface Gestures
  surface.addEventListener("touchstart", (e) => {
    e.preventDefault();
    touchCount = e.touches.length;
    startTime = Date.now();
    isMoving = false;

    if (touchCount === 1) {
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      lastX = startX;
      lastY = startY;
    } else if (touchCount === 2) {
      startY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
      lastY = startY;
    }
  }, { passive: false });

  surface.addEventListener("touchmove", (e) => {
    e.preventDefault();
    touchCount = e.touches.length;

    if (touchCount === 1) {
      const currentX = e.touches[0].clientX;
      const currentY = e.touches[0].clientY;
      const dx = currentX - lastX;
      const dy = currentY - lastY;

      if (Math.abs(dx) > 0.4 || Math.abs(dy) > 0.4) {
        isMoving = true;
        // Non-linear acceleration curve for micro precision + high speed travel
        const distance = Math.hypot(dx, dy);
        const accel = distance > 15 ? 1.4 : (distance > 5 ? 1.1 : 0.85);
        sendWs({ type: "mouse_move", dx: dx, dy: dy, speed: mouseSpeed * accel });
      }

      lastX = currentX;
      lastY = currentY;
    } else if (touchCount === 2) {
      const currentY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
      const dy = currentY - lastY;
      
      if (Math.abs(dy) > 1.5) {
        isMoving = true;
        sendWs({ type: "mouse_scroll", dy: dy });
      }
      lastY = currentY;
    }
  }, { passive: false });

  surface.addEventListener("touchend", (e) => {
    e.preventDefault();
    const duration = Date.now() - startTime;

    // Detect Tap (short duration, minimal movement)
    if (!isMoving && duration < 250) {
      if (touchCount === 1) {
        sendWs({ type: "mouse_click", button: "left", clicks: 1 });
        if (navigator.vibrate) navigator.vibrate(20);
      } else if (touchCount === 2) {
        sendWs({ type: "mouse_click", button: "right", clicks: 1 });
        if (navigator.vibrate) navigator.vibrate(40);
      }
    }
    touchCount = e.touches.length;
  }, { passive: false });

  // Dedicated Vertical Scroll Strip
  let scrollStartY = 0;
  scrollStrip.addEventListener("touchstart", (e) => {
    e.preventDefault();
    scrollStartY = e.touches[0].clientY;
  }, { passive: false });

  scrollStrip.addEventListener("touchmove", (e) => {
    e.preventDefault();
    const currentY = e.touches[0].clientY;
    const dy = currentY - scrollStartY;
    if (Math.abs(dy) > 2) {
      sendWs({ type: "mouse_scroll", dy: dy * 1.5 });
      scrollStartY = currentY;
      if (navigator.vibrate) navigator.vibrate(10);
    }
  }, { passive: false });

  // 5-Button Mouse Action Controls
  document.getElementById("btn-lclick").addEventListener("click", () => {
    sendWs({ type: "mouse_click", button: "left", clicks: 1 });
    if (navigator.vibrate) navigator.vibrate(20);
  });

  document.getElementById("btn-dclick").addEventListener("click", () => {
    sendWs({ type: "mouse_click", button: "left", clicks: 2 });
    if (navigator.vibrate) navigator.vibrate(40);
  });

  document.getElementById("btn-mclick").addEventListener("click", () => {
    sendWs({ type: "mouse_click", button: "middle", clicks: 1 });
    if (navigator.vibrate) navigator.vibrate(30);
  });

  document.getElementById("btn-rclick").addEventListener("click", () => {
    sendWs({ type: "mouse_click", button: "right", clicks: 1 });
    if (navigator.vibrate) navigator.vibrate(35);
  });

  const btnDrag = document.getElementById("btn-draglock");
  btnDrag.addEventListener("click", () => {
    isDragLocked = !isDragLocked;
    if (isDragLocked) {
      btnDrag.classList.add("active");
      sendWs({ type: "mouse_down", button: "left" });
    } else {
      btnDrag.classList.remove("active");
      sendWs({ type: "mouse_up", button: "left" });
    }
  });
}

function handleGyroOrientation(e) {
  if (!gyroActive || e.gamma === null || e.beta === null) return;

  if (lastGyroGamma === null) {
    lastGyroGamma = e.gamma;
    lastGyroBeta = e.beta;
    return;
  }

  const dGamma = e.gamma - lastGyroGamma;
  const dBeta = e.beta - lastGyroBeta;

  if (Math.abs(dGamma) > 0.3 || Math.abs(dBeta) > 0.3) {
    sendWs({
      type: "mouse_move",
      dx: dGamma * 2.5 * mouseSpeed,
      dy: dBeta * 2.5 * mouseSpeed,
      speed: 1.0
    });
  }

  lastGyroGamma = e.gamma;
  lastGyroBeta = e.beta;
}

// ================= LIVE SCREEN STREAM & INTERACTIVE ZOOM =================

let screenZoom = 1.0;
let panOffsetX = 0;
let panOffsetY = 0;
let isPinchPanning = false;
let pinchStartDist = 0;
let pinchStartZoom = 1.0;
let pinchStartMidX = 0;
let pinchStartMidY = 0;
let lastMidX = 0;
let lastMidY = 0;
let touchStartPanX = 0;
let touchStartPanY = 0;
let isSingleDragPanning = false;
let lastTapTime = 0;
let zoomHudTimer = null;

function applyZoomTransform(animate = false) {
  const wrapper = document.getElementById("screen-transform-wrapper");
  const screenContainer = document.getElementById("screen-container");
  const btnZoomLevel = document.getElementById("btn-zoom-reset");
  const zoomHud = document.getElementById("zoom-hud");
  if (!wrapper || !screenContainer) return;

  // Clamp pan boundaries based on zoom level
  if (screenZoom <= 1.02) {
    screenZoom = 1.0;
    panOffsetX = 0;
    panOffsetY = 0;
  } else {
    const cRect = screenContainer.getBoundingClientRect();
    const maxPanX = Math.max(0, (screenZoom - 1) * (cRect.width / 2) + 40);
    const maxPanY = Math.max(0, (screenZoom - 1) * (cRect.height / 2) + 40);
    panOffsetX = Math.max(-maxPanX, Math.min(maxPanX, panOffsetX));
    panOffsetY = Math.max(-maxPanY, Math.min(maxPanY, panOffsetY));
  }

  if (animate) {
    wrapper.classList.add("animating");
    setTimeout(() => wrapper.classList.remove("animating"), 260);
  } else {
    wrapper.classList.remove("animating");
  }

  wrapper.style.transform = `translate(${panOffsetX.toFixed(1)}px, ${panOffsetY.toFixed(1)}px) scale(${screenZoom.toFixed(2)})`;

  if (btnZoomLevel) {
    btnZoomLevel.textContent = `${screenZoom.toFixed(1)}x`;
  }

  // Show floating HUD feedback
  if (zoomHud) {
    zoomHud.textContent = `${screenZoom.toFixed(1)}x Zoom`;
    zoomHud.classList.add("visible");
    if (zoomHudTimer) clearTimeout(zoomHudTimer);
    zoomHudTimer = setTimeout(() => zoomHud.classList.remove("visible"), 1200);
  }
}

function setZoom(newZoom, animate = true) {
  screenZoom = Math.max(1.0, Math.min(4.5, newZoom));
  applyZoomTransform(animate);
}

function setupScreenStream() {
  const canvas = document.getElementById("screen-canvas");
  const screenContainer = document.getElementById("screen-container");
  const btnRefresh = document.getElementById("btn-screen-refresh");
  const btnFullscreen = document.getElementById("btn-screen-fullscreen");
  
  // Zoom Controls
  const btnZoomIn = document.getElementById("btn-zoom-in");
  const btnZoomOut = document.getElementById("btn-zoom-out");
  const btnZoomReset = document.getElementById("btn-zoom-reset");
  const btnZoomFit = document.getElementById("btn-zoom-fit");

  if (btnZoomIn) btnZoomIn.addEventListener("click", () => setZoom(screenZoom + 0.5, true));
  if (btnZoomOut) btnZoomOut.addEventListener("click", () => setZoom(screenZoom - 0.5, true));
  if (btnZoomReset) btnZoomReset.addEventListener("click", () => setZoom(1.0, true));
  if (btnZoomFit) btnZoomFit.addEventListener("click", () => setZoom(screenZoom === 1.0 ? 2.2 : 1.0, true));

  // Quality Mode Pill Buttons
  document.querySelectorAll(".quality-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-mode");
      setScreenQuality(mode);
    });
  });

  // Mouse wheel zoom support (only active in Mobile Mode)
  screenContainer.addEventListener("wheel", (e) => {
    if (currentUIMode === "desktop") return;
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.25 : -0.25;
    setZoom(screenZoom + delta, false);
  }, { passive: false });

  let touchStartTime = 0;
  let touchStartPos = { x: 0, y: 0 };
  let isLongPress = false;
  let longPressTimer = null;

  screenContainer.addEventListener("touchstart", (e) => {
    if (e.touches.length === 1) {
      isPinchPanning = false;
      isSingleDragPanning = false;
      touchStartTime = Date.now();
      touchStartPos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      touchStartPanX = panOffsetX;
      touchStartPanY = panOffsetY;
      isLongPress = false;

      longPressTimer = setTimeout(() => {
        isLongPress = true;
        const rect = canvas.getBoundingClientRect();
        const xPct = (touchStartPos.x - rect.left) / rect.width;
        const yPct = (touchStartPos.y - rect.top) / rect.height;
        if (xPct >= 0 && xPct <= 1 && yPct >= 0 && yPct <= 1) {
          sendWs({ type: "screen_click", x_pct: xPct, y_pct: yPct, button: "right", clicks: 1 });
          if (navigator.vibrate) navigator.vibrate(60);
          setTimeout(fetchNextScreenFrame, 80);
        }
      }, 450);
    } else if (e.touches.length === 2) {
      if (longPressTimer) clearTimeout(longPressTimer);
      isPinchPanning = true;
      isSingleDragPanning = false;
      isLongPress = false;
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      pinchStartDist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      pinchStartZoom = screenZoom;
      pinchStartMidX = (t1.clientX + t2.clientX) / 2;
      pinchStartMidY = (t1.clientY + t2.clientY) / 2;
      lastMidX = pinchStartMidX;
      lastMidY = pinchStartMidY;
    }
  }, { passive: false });

  screenContainer.addEventListener("touchmove", (e) => {
    e.preventDefault();

    if (e.touches.length === 1 && !isPinchPanning) {
      const dx = e.touches[0].clientX - touchStartPos.x;
      const dy = e.touches[0].clientY - touchStartPos.y;
      
      if (Math.hypot(dx, dy) > 8) {
        if (longPressTimer) clearTimeout(longPressTimer);
        // If zoomed in, drag to pan view smoothly
        if (screenZoom > 1.05) {
          isSingleDragPanning = true;
          panOffsetX = touchStartPanX + dx;
          panOffsetY = touchStartPanY + dy;
          applyZoomTransform(false);
        }
      }
    } else if (e.touches.length === 2) {
      isPinchPanning = true;
      if (longPressTimer) clearTimeout(longPressTimer);
      
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const curDist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const curMidX = (t1.clientX + t2.clientX) / 2;
      const curMidY = (t1.clientY + t2.clientY) / 2;

      // Real-time Pinch Scaling & Center Tracking
      if (pinchStartDist > 5) {
        const factor = curDist / pinchStartDist;
        screenZoom = Math.max(1.0, Math.min(5.0, pinchStartZoom * factor));
        panOffsetX += (curMidX - lastMidX);
        panOffsetY += (curMidY - lastMidY);
        lastMidX = curMidX;
        lastMidY = curMidY;
        applyZoomTransform(false);
      }
    }
  }, { passive: false });

  screenContainer.addEventListener("touchend", (e) => {
    if (longPressTimer) clearTimeout(longPressTimer);

    if (e.touches.length === 0) {
      const duration = Date.now() - touchStartTime;
      const dx = Math.abs(touchStartPos.x - (e.changedTouches[0] ? e.changedTouches[0].clientX : touchStartPos.x));
      const dy = Math.abs(touchStartPos.y - (e.changedTouches[0] ? e.changedTouches[0].clientY : touchStartPos.y));

      // Snap back to 1.0 if zoom is barely changed
      if (screenZoom < 1.08 && screenZoom !== 1.0) {
        setZoom(1.0, true);
      }

      if (!isLongPress && !isSingleDragPanning && !isPinchPanning && duration < 320 && dx < 12 && dy < 12) {
        const now = Date.now();
        // Double-tap detector: Quick toggle between 1.0x and 2.2x
        if (now - lastTapTime < 280) {
          lastTapTime = 0;
          if (screenZoom > 1.1) {
            setZoom(1.0, true);
          } else {
            setZoom(2.2, true);
          }
          if (navigator.vibrate) navigator.vibrate(30);
        } else {
          lastTapTime = now;
          // Single tap -> Translate click coordinates accurately even under zoom/pan
          const rect = canvas.getBoundingClientRect();
          const clickX = touchStartPos.x;
          const clickY = touchStartPos.y;
          const xPct = (clickX - rect.left) / rect.width;
          const yPct = (clickY - rect.top) / rect.height;

          if (xPct >= 0 && xPct <= 1 && yPct >= 0 && yPct <= 1) {
            sendWs({ type: "screen_click", x_pct: xPct, y_pct: yPct, button: "left", clicks: 1 });
            if (navigator.vibrate) navigator.vibrate(20);
            setTimeout(fetchNextScreenFrame, 80);
          }
        }
      }
      isPinchPanning = false;
      isSingleDragPanning = false;
    } else if (e.touches.length === 1) {
      // Transitioning from 2 fingers to 1 finger
      isPinchPanning = false;
      touchStartPos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      touchStartPanX = panOffsetX;
      touchStartPanY = panOffsetY;
    }
  }, { passive: false });

  btnRefresh.addEventListener("click", fetchNextScreenFrame);

  btnFullscreen.addEventListener("click", () => {
    if (!document.fullscreenElement) {
      screenContainer.requestFullscreen().catch(err => console.log(err));
    } else {
      document.exitFullscreen();
    }
  });
}

// Screen Quality & Streaming Config
let currentScreenMode = "ultra";
let screenWs = null;
let frameCount = 0;
let lastFpsTime = Date.now();
let currentFps = 0;
let isScreenWsActive = false;

const QUALITY_PRESETS = {
  ultra: { scale: 1.0, quality: 90, fps: 60, name: "Ultra HD" },
  turbo: { scale: 0.75, quality: 75, fps: 60, name: "60 FPS Turbo" },
  balanced: { scale: 0.65, quality: 55, fps: 30, name: "Balanced" },
  eco: { scale: 0.50, quality: 40, fps: 15, name: "Eco" }
};

function updateQualityPillsUI(mode) {
  document.querySelectorAll(".quality-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-mode") === mode);
  });
  document.querySelectorAll(".floating-btn[data-fmode]").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-fmode") === mode);
  });
}

function setScreenQuality(mode) {
  if (!QUALITY_PRESETS[mode]) return;
  currentScreenMode = mode;
  updateQualityPillsUI(mode);

  if (screenWs && screenWs.readyState === WebSocket.OPEN) {
    const cfg = QUALITY_PRESETS[mode];
    screenWs.send(JSON.stringify({
      type: "config",
      scale: cfg.scale,
      quality: cfg.quality,
      fps: cfg.fps
    }));
  }
  const badge = document.getElementById("stream-stats-badge");
  if (badge) {
    badge.textContent = `${QUALITY_PRESETS[mode].name}`;
  }
  const floatBadge = document.getElementById("float-stream-stats");
  if (floatBadge) {
    floatBadge.textContent = `${QUALITY_PRESETS[mode].name}`;
  }
}

function startScreenStream() {
  screenStreamActive = true;
  startWsScreenStream();
}

function stopScreenStream() {
  screenStreamActive = false;
  if (screenWs) {
    try {
      screenWs.send(JSON.stringify({ type: "stop" }));
      screenWs.close();
    } catch(e) {}
    screenWs = null;
  }
  if (screenTimer) clearTimeout(screenTimer);
}

function startWsScreenStream() {
  if (!screenStreamActive || !currentPin) return;

  const wsUrl = getWsUrl("/ws/screen");

  try {
    if (screenWs) {
      try { screenWs.close(); } catch(e) {}
    }

    screenWs = new WebSocket(wsUrl);
    screenWs.binaryType = "blob";

    const cfg = QUALITY_PRESETS[currentScreenMode] || QUALITY_PRESETS.ultra;

    screenWs.onopen = () => {
      isScreenWsActive = true;
      screenWs.send(JSON.stringify({
        pin: currentPin,
        scale: cfg.scale,
        quality: cfg.quality,
        fps: cfg.fps
      }));
    };

    screenWs.onmessage = async (event) => {
      if (typeof event.data === "string") {
        try {
          const meta = JSON.parse(event.data);
          if (meta.type === "stream_ready") {
            const spinner = document.getElementById("screen-spinner");
            if (spinner) spinner.style.display = "none";
          }
        } catch(e) {}
        return;
      }

      // Render binary frame to canvas
      const canvas = document.getElementById("screen-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d", { alpha: false });

      try {
        if ('createImageBitmap' in window) {
          const bitmap = await createImageBitmap(event.data);
          if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
          }
          ctx.imageSmoothingEnabled = true;
          ctx.imageSmoothingQuality = 'high';
          ctx.drawImage(bitmap, 0, 0);
          bitmap.close();
        } else {
          const img = new Image();
          const url = URL.createObjectURL(event.data);
          img.onload = () => {
            if (canvas.width !== img.width || canvas.height !== img.height) {
              canvas.width = img.width;
              canvas.height = img.height;
            }
            ctx.drawImage(img, 0, 0);
            URL.revokeObjectURL(url);
          };
          img.src = url;
        }

        const spinner = document.getElementById("screen-spinner");
        if (spinner) spinner.style.display = "none";

        // FPS calculation
        frameCount++;
        const now = Date.now();
        if (now - lastFpsTime >= 1000) {
          currentFps = frameCount;
          frameCount = 0;
          lastFpsTime = now;
          const badge = document.getElementById("stream-stats-badge");
          if (badge) {
            badge.textContent = `${currentFps} FPS • ${QUALITY_PRESETS[currentScreenMode].name}`;
          }
          const floatBadge = document.getElementById("float-stream-stats");
          if (floatBadge) {
            floatBadge.textContent = `${currentFps} FPS`;
          }
        }
      } catch (err) {
        console.warn("Screen draw error:", err);
      }
    };

    screenWs.onerror = () => {
      isScreenWsActive = false;
    };

    screenWs.onclose = () => {
      isScreenWsActive = false;
      if (screenStreamActive) {
        setTimeout(fetchNextScreenFrame, 600);
      }
    };

  } catch (err) {
    console.warn("WebSocket screen error:", err);
    fetchNextScreenFrame();
  }
}

let isFetchingFrame = false;
let screenPollDelay = 200;
let lastInteractionTime = Date.now();

function boostScreenFps() {
  lastInteractionTime = Date.now();
  screenPollDelay = 120;
}

async function fetchNextScreenFrame() {
  if (!screenStreamActive || !isConnected || isFetchingFrame || isScreenWsActive) return;

  const canvas = document.getElementById("screen-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d", { alpha: false });
  const spinner = document.getElementById("screen-spinner");
  isFetchingFrame = true;

  const cfg = QUALITY_PRESETS[currentScreenMode] || QUALITY_PRESETS.ultra;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 2500);

  try {
    const res = await fetch(getApiUrl(`/api/screenshot?pin=${currentPin}&q=${cfg.quality}&scale=${cfg.scale}&t=${Date.now()}`), {
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const blob = await res.blob();
      if ('createImageBitmap' in window) {
        const bitmap = await createImageBitmap(blob);
        if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
        }
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(bitmap, 0, 0);
        bitmap.close();
      } else {
        const img = new Image();
        const url = URL.createObjectURL(blob);
        img.onload = () => {
          if (canvas.width !== img.width || canvas.height !== img.height) {
            canvas.width = img.width;
            canvas.height = img.height;
          }
          ctx.drawImage(img, 0, 0);
          URL.revokeObjectURL(url);
        };
        img.src = url;
      }
      if (spinner) spinner.style.display = "none";

      frameCount++;
      const now = Date.now();
      if (now - lastFpsTime >= 1000) {
        currentFps = frameCount;
        frameCount = 0;
        lastFpsTime = now;
        const badge = document.getElementById("stream-stats-badge");
        if (badge) {
          badge.textContent = `${currentFps} FPS • HTTP`;
        }
        const floatBadge = document.getElementById("float-stream-stats");
        if (floatBadge) {
          floatBadge.textContent = `${currentFps} FPS • HTTP`;
        }
      }
    }
  } catch (err) {
    console.warn("Screen frame error:", err);
    screenPollDelay = 800;
  } finally {
    isFetchingFrame = false;
    if (screenStreamActive && !isScreenWsActive) {
      screenTimer = setTimeout(fetchNextScreenFrame, screenPollDelay);
    }
  }
}

// ================= MEDIA & ACTIONS =================

async function sendAction(action) {
  if (navigator.vibrate) navigator.vibrate(30);
  try {
    await fetch(getApiUrl("/api/action"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: currentPin, action: action })
    });
  } catch (e) {
    console.error("Action error:", e);
  }
}

async function launchApp(appName) {
  if (navigator.vibrate) navigator.vibrate(30);
  try {
    await fetch(getApiUrl("/api/action"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: currentPin, action: "launch_app", app: appName })
    });
  } catch (e) {
    console.error("Launch app error:", e);
  }
}

function confirmAction(action, promptText) {
  if (confirm(promptText)) {
    sendAction(action);
  }
}

// ================= KEYBOARD & SHORTCUTS =================

function setupShortcuts() {
  const directInput = document.getElementById("direct-type-input");
  const btnSendText = document.getElementById("btn-send-text");

  btnSendText.addEventListener("click", () => {
    const text = directInput.value;
    if (text) {
      sendWs({ type: "type_text", text: text, mode: "paste" });
      directInput.value = "";
    }
  });

  directInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      btnSendText.click();
    }
  });
}

function setupClipboard() {
  document.getElementById("btn-get-clipboard").addEventListener("click", () => {
    sendWs({ type: "get_clipboard" });
  });

  document.getElementById("btn-set-clipboard").addEventListener("click", () => {
    const text = document.getElementById("clipboard-input").value;
    if (text) {
      sendWs({ type: "set_clipboard", text: text });
    }
  });
}

function sendHotkey(keys) {
  if (navigator.vibrate) navigator.vibrate(20);
  sendWs({ type: "hotkey", keys: keys });
}

function sendKeyPress(key) {
  if (navigator.vibrate) navigator.vibrate(20);
  sendWs({ type: "key_press", key: key });
}

// ================= TERMINAL =================

function setupTerminal() {
  const termInput = document.getElementById("term-input");
  const btnRun = document.getElementById("btn-term-run");
  const btnClear = document.getElementById("btn-clear-term");
  const termOutput = document.getElementById("term-output");

  btnRun.addEventListener("click", () => {
    const cmd = termInput.value.trim();
    if (!cmd) return;

    appendTerminalOutput(`PS > ${cmd}\n`, "command");
    sendWs({ type: "terminal_exec", command: cmd, cmd_id: String(Date.now()) });
    termInput.value = "";
  });

  termInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      btnRun.click();
    }
  });

  btnClear.addEventListener("click", () => {
    termOutput.innerHTML = "";
  });
}

function appendTerminalOutput(text, type = "stdout") {
  const termOutput = document.getElementById("term-output");
  const span = document.createElement("span");
  span.className = `term-${type}`;
  span.textContent = text;
  termOutput.appendChild(span);
  termOutput.scrollTop = termOutput.scrollHeight;
}

// ================= FILE EXPLORER =================

function setupFiles() {
  const uploadInput = document.getElementById("file-upload-input");
  uploadInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("pin", currentPin);
    formData.append("dest_dir", currentPath);
    formData.append("file", file);

    try {
      const res = await fetch(getApiUrl("/api/files/upload"), { method: "POST", body: formData });
      if (res.ok) {
        alert("Upload successful: " + file.name);
        loadDirectory(currentPath);
      } else {
        alert("Upload failed.");
      }
    } catch (err) {
      alert("Error: " + err.message);
    }
  });
}

async function loadDirectory(path) {
  const container = document.getElementById("files-container");
  const breadcrumb = document.getElementById("file-breadcrumb");
  container.innerHTML = `<div class="spinner"></div>`;

  try {
    const res = await fetch(getApiUrl(`/api/files?pin=${currentPin}&path=${encodeURIComponent(path)}`));
    if (!res.ok) throw new Error("Failed to load path");

    const data = await res.json();
    currentPath = data.current_path;
    breadcrumb.textContent = currentPath;
    container.innerHTML = "";

    data.items.forEach((item) => {
      const el = document.createElement("div");
      el.className = "file-item";

      const icon = item.is_dir ? "fa-solid fa-folder" : "fa-solid fa-file";
      const iconColor = item.is_dir ? "color: #ffd600;" : "color: #8b949e;";

      el.innerHTML = `
        <div class="file-name">
          <i class="${icon}" style="${iconColor}"></i>
          <span>${item.name}</span>
        </div>
      `;

      el.addEventListener("click", () => {
        if (item.is_dir) {
          loadDirectory(item.path);
        } else {
          // Download file
          window.location.href = getApiUrl(`/api/files/download?pin=${currentPin}&path=${encodeURIComponent(item.path)}`);
        }
      });

      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<div style="color: var(--accent-red); padding: 10px;">Error: ${err.message}</div>`;
  }
}

// ================= INTERACTIVE APP SEARCH & LAUNCHER =================

let allInstalledApps = [];

async function setupAppSearch() {
  const searchInput = document.getElementById("app-search-input");
  const clearBtn = document.getElementById("btn-clear-app-search");
  const resultsContainer = document.getElementById("app-results-container");

  // Load apps in background
  try {
    const res = await fetch(getApiUrl(`/api/apps?pin=${currentPin}`));
    if (res.ok) {
      const data = await res.json();
      allInstalledApps = data.apps || [];
      renderAppResults(allInstalledApps.slice(0, 16));
    }
  } catch (e) {
    console.warn("App list fetch error:", e);
  }

  // Live typing search
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    if (q.length > 0) {
      clearBtn.style.display = "block";
      const filtered = allInstalledApps.filter(app => app.name.toLowerCase().includes(q));
      renderAppResults(filtered);
    } else {
      clearBtn.style.display = "none";
      renderAppResults(allInstalledApps.slice(0, 16));
    }
  });

  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const q = searchInput.value.trim();
      if (q) {
        // If exact or top match exists, launch it
        const filtered = allInstalledApps.filter(app => app.name.toLowerCase().includes(q.toLowerCase()));
        if (filtered.length > 0) {
          launchSpecificApp(filtered[0]);
          searchInput.value = "";
          clearBtn.style.display = "none";
        }
      }
    }
  });

  clearBtn.addEventListener("click", () => {
    searchInput.value = "";
    clearBtn.style.display = "none";
    renderAppResults(allInstalledApps.slice(0, 16));
  });
}

function renderAppResults(apps) {
  const container = document.getElementById("app-results-container");
  if (!container) return;
  container.innerHTML = "";

  if (apps.length === 0) {
    container.innerHTML = `<div style="color: var(--text-muted); font-size: 0.8rem; padding: 10px; grid-column: 1 / -1; text-align: center;">No apps found. Try Windows Search.</div>`;
    return;
  }

  apps.forEach(app => {
    const card = document.createElement("div");
    card.className = "app-result-card";
    
    // Choose appropriate icon
    let iconClass = "fa-solid fa-cube";
    const nameLower = app.name.toLowerCase();
    if (nameLower.includes("chrome") || nameLower.includes("edge") || nameLower.includes("browser") || nameLower.includes("brave") || nameLower.includes("firefox")) {
      iconClass = "fa-brands fa-chrome";
    } else if (nameLower.includes("code") || nameLower.includes("studio") || nameLower.includes("antigravity")) {
      iconClass = "fa-solid fa-code";
    } else if (nameLower.includes("discord")) {
      iconClass = "fa-brands fa-discord";
    } else if (nameLower.includes("spotify") || nameLower.includes("music")) {
      iconClass = "fa-brands fa-spotify";
    } else if (nameLower.includes("calc")) {
      iconClass = "fa-solid fa-calculator";
    } else if (nameLower.includes("settings") || nameLower.includes("control")) {
      iconClass = "fa-solid fa-gear";
    } else if (nameLower.includes("word") || nameLower.includes("note") || nameLower.includes("doc")) {
      iconClass = "fa-solid fa-file-word";
    } else if (nameLower.includes("excel") || nameLower.includes("sheet")) {
      iconClass = "fa-solid fa-file-excel";
    } else if (nameLower.includes("terminal") || nameLower.includes("powershell") || nameLower.includes("cmd")) {
      iconClass = "fa-solid fa-terminal";
    }

    card.innerHTML = `<i class="${iconClass}"></i><span>${app.name}</span>`;
    card.addEventListener("click", () => launchSpecificApp(app));
    container.appendChild(card);
  });
}

async function launchSpecificApp(app) {
  if (navigator.vibrate) navigator.vibrate(30);
  try {
    await fetch(getApiUrl("/api/apps/launch"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: currentPin, appid: app.appid, name: app.name })
    });
    alert("Launched: " + app.name);
  } catch (e) {
    console.error("App launch error:", e);
  }
}

// ==========================================================================
// DUAL-MODE CONTROLLER: LAPTOP / SECOND SCREEN vs MOBILE TOUCHPAD
// ==========================================================================

let currentUIMode = "mobile"; // "mobile" or "desktop"
let mouseMovePending = false;
let nextMousePos = null;

function setUIMode(mode, autoStarted = false) {
  currentUIMode = mode;
  localStorage.setItem("remote_hub_ui_mode", mode);

  const floatingBar = document.getElementById("desktop-floating-bar");
  const modeBtnLabel = document.getElementById("mode-btn-label");
  const modeBtn = document.getElementById("btn-toggle-ui-mode");

  if (mode === "desktop") {
    appContainer.classList.add("desktop-mode");
    if (floatingBar) floatingBar.classList.remove("hidden");
    if (modeBtnLabel) modeBtnLabel.textContent = "Mobile Mode";
    if (modeBtn) modeBtn.innerHTML = `<i class="fa-solid fa-mobile-screen"></i> <span>Mobile Mode</span>`;

    // Make sure screen view is active
    document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
    const screenPanel = document.getElementById("view-screen");
    if (screenPanel) screenPanel.classList.add("active");

    // Reset mobile zoom when entering desktop mode for 1:1 pixel fidelity
    setZoom(1.0, false);

    // Auto-start screen stream
    if (isConnected) {
      startScreenStream();
    }
  } else {
    appContainer.classList.remove("desktop-mode");
    if (floatingBar) floatingBar.classList.add("hidden");
    if (modeBtnLabel) modeBtnLabel.textContent = "Laptop Mode";
    if (modeBtn) modeBtn.innerHTML = `<i class="fa-solid fa-laptop"></i> <span>Laptop Mode</span>`;

    // Reset to touchpad view if exiting desktop mode
    const touchpadNavBtn = document.querySelector('.nav-item[data-target="view-touchpad"]');
    if (touchpadNavBtn && !autoStarted) {
      touchpadNavBtn.click();
    }
  }
}

function toggleUIMode() {
  setUIMode(currentUIMode === "desktop" ? "mobile" : "desktop");
}

function setupDesktopInputPassThrough() {
  const canvas = document.getElementById("screen-canvas");
  if (!canvas) return;

  // 1. Physical Mouse Movement (throttled to 60fps via requestAnimationFrame)
  function handleCanvasPointerMove(e) {
    if (currentUIMode !== "desktop" || !isConnected) return;
    const rect = canvas.getBoundingClientRect();
    const xPct = (e.clientX - rect.left) / rect.width;
    const yPct = (e.clientY - rect.top) / rect.height;

    if (xPct >= 0 && xPct <= 1 && yPct >= 0 && yPct <= 1) {
      nextMousePos = { xPct, yPct };
      if (!mouseMovePending) {
        mouseMovePending = true;
        requestAnimationFrame(() => {
          if (nextMousePos) {
            sendWs({ type: "mouse_move_to", x_pct: nextMousePos.xPct, y_pct: nextMousePos.yPct });
          }
          mouseMovePending = false;
        });
      }
    }
  }

  // 2. Physical Mouse Down
  function handleCanvasPointerDown(e) {
    if (currentUIMode !== "desktop" || !isConnected) return;
    if (e.pointerType === "touch") return; // Touch is handled separately

    const rect = canvas.getBoundingClientRect();
    const xPct = (e.clientX - rect.left) / rect.width;
    const yPct = (e.clientY - rect.top) / rect.height;

    if (xPct >= 0 && xPct <= 1 && yPct >= 0 && yPct <= 1) {
      const btn = e.button === 2 ? "right" : (e.button === 1 ? "middle" : "left");
      sendWs({ type: "mouse_down", button: btn, x_pct: xPct, y_pct: yPct });
    }
  }

  // 3. Physical Mouse Up
  function handleCanvasPointerUp(e) {
    if (currentUIMode !== "desktop" || !isConnected) return;
    if (e.pointerType === "touch") return;

    const rect = canvas.getBoundingClientRect();
    const xPct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const yPct = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const btn = e.button === 2 ? "right" : (e.button === 1 ? "middle" : "left");
    sendWs({ type: "mouse_up", button: btn, x_pct: xPct, y_pct: yPct });
  }

  // 4. Suppress browser right-click menu on canvas so Windows receives it
  canvas.addEventListener("contextmenu", (e) => {
    if (currentUIMode === "desktop") {
      e.preventDefault();
    }
  });

  // 5. Wheel scrolling pass-through in Desktop mode
  canvas.addEventListener("wheel", (e) => {
    if (currentUIMode === "desktop" && isConnected) {
      e.preventDefault();
      sendWs({ type: "mouse_scroll", dy: e.deltaY, dx: e.deltaX });
    }
  }, { passive: false });

  // 6. Double-click pass-through
  canvas.addEventListener("dblclick", (e) => {
    if (currentUIMode !== "desktop" || !isConnected) return;
    const rect = canvas.getBoundingClientRect();
    const xPct = (e.clientX - rect.left) / rect.width;
    const yPct = (e.clientY - rect.top) / rect.height;
    if (xPct >= 0 && xPct <= 1 && yPct >= 0 && yPct <= 1) {
      sendWs({ type: "mouse_click", button: "left", clicks: 2, x_pct: xPct, y_pct: yPct });
    }
  });

  canvas.addEventListener("pointermove", handleCanvasPointerMove);
  canvas.addEventListener("pointerdown", handleCanvasPointerDown);
  window.addEventListener("pointerup", handleCanvasPointerUp);

  // 7. Global Physical Keyboard Listener in Desktop Mode
  window.addEventListener("keydown", (e) => {
    if (currentUIMode !== "desktop" || !isConnected) return;

    // Do not capture if user is typing into an input field or modal
    const tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;

    // Prevent browser default actions for keys like Tab, Backspace, Arrows, F5, F11, etc.
    const browserIntercept = [
      "Tab", "Backspace", "Space", " ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
      "Escape", "F5", "F11", "Alt", "Meta", "Control"
    ];
    if (browserIntercept.includes(e.key) || (e.ctrlKey && ["c", "v", "z", "a", "s", "x", "w", "t", "r"].includes(e.key.toLowerCase()))) {
      e.preventDefault();
    }

    sendWs({ type: "key_down", key: e.key.toLowerCase() });
  });

  window.addEventListener("keyup", (e) => {
    if (currentUIMode !== "desktop" || !isConnected) return;
    const tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;

    sendWs({ type: "key_up", key: e.key.toLowerCase() });
  });

  // Setup UI mode toggle buttons
  const btnToggleMode = document.getElementById("btn-toggle-ui-mode");
  if (btnToggleMode) btnToggleMode.addEventListener("click", toggleUIMode);

  const btnFloatMode = document.getElementById("btn-float-mode");
  if (btnFloatMode) btnFloatMode.addEventListener("click", toggleUIMode);

  // Floating Fullscreen toggle button
  const btnFloatFullscreen = document.getElementById("btn-float-fullscreen");
  if (btnFloatFullscreen) {
    btnFloatFullscreen.addEventListener("click", () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(err => console.log(err));
      } else {
        document.exitFullscreen();
      }
    });
  }

  // Floating Shortcuts Popover Menu
  const btnFloatShortcuts = document.getElementById("btn-float-shortcuts");
  const popover = document.getElementById("floating-shortcuts-popover");
  if (btnFloatShortcuts && popover) {
    btnFloatShortcuts.addEventListener("click", (e) => {
      e.stopPropagation();
      popover.classList.toggle("hidden");
    });
    document.addEventListener("click", () => {
      popover.classList.add("hidden");
    });
  }

  // Floating Quality Selector Buttons
  document.querySelectorAll(".floating-btn[data-fmode]").forEach(btn => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-fmode");
      setScreenQuality(mode);
    });
  });

  // Floating Exit / Switch PC Button
  const btnFloatSwitchPc = document.getElementById("btn-float-switch-pc");
  const hubOverlay = document.getElementById("device-hub-overlay");
  if (btnFloatSwitchPc && hubOverlay) {
    btnFloatSwitchPc.addEventListener("click", () => {
      hubOverlay.classList.remove("hidden");
    });
  }
}

