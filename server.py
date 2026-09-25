"""
Laptop Remote Hub Server
-------------------------
High-performance FastAPI & WebSocket backend for controlling Windows PC from a mobile phone.
Features:
- Ultra-low latency touch trackpad, mouse clicking, dragging, and scrolling.
- Real-time desktop screen streaming & tap-to-point clicking.
- Full virtual keyboard, hotkey execution, text typing & clipboard sync.
- Remote PowerShell terminal execution with live streaming output.
- System metrics (CPU, RAM, Battery, Wi-Fi status, SRM Sentinel).
- Media controls & power actions (Volume, Mute, Lock, Sleep, Restart, Shutdown).
- Mobile file explorer & upload/download manager.
"""

import os
import sys
import io
import time
import json
import asyncio
import subprocess
import threading
from typing import Optional, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "hub_server.log")

def make_stream_safe(stream, fallback_path):
    try:
        if stream is None:
            return open(fallback_path, "a", encoding="utf-8", buffering=1)
        stream.write("")
        stream.flush()
        return stream
    except Exception:
        try:
            return open(fallback_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            return open(os.devnull, "w")

if sys.stdin is None:
    try:
        sys.stdin = open(os.devnull, "r")
    except Exception:
        pass

sys.stdout = make_stream_safe(sys.stdout, LOG_FILE)
sys.stderr = make_stream_safe(sys.stderr, LOG_FILE)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import pyautogui
import mss
import psutil
from PIL import Image

# Import Screen Capturer & SRM Sentinel
from screen_capturer import capture_desktop_jpeg, get_screen_size, attach_interactive_desktop
from srm_sentinel import status_data as srm_status, start_sentinel_thread, prevent_windows_sleep
from tunnel_manager import Tunnel

# Attach to interactive session
attach_interactive_desktop()

# PyAutoGUI configurations
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.001

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
AUTH_PIN = "1234"  # Default security PIN

app = FastAPI(title="Laptop Remote Hub")

# Enable Cross-Origin Resource Sharing (CORS) for GitHub Pages remote control
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_screen_dimensions():
    try:
        w, h = get_screen_size()
        return w, h
    except Exception:
        return 1920, 1080


def capture_screen_jpeg(quality: int = 45, scale: float = 0.65) -> bytes:
    """Captures screenshot using ultra-fast Win32 GDI engine."""
    return capture_desktop_jpeg(scale=scale, quality=quality)


def get_system_metrics() -> Dict[str, Any]:
    """Gathers live system stats: CPU, RAM, Battery, Active Window."""
    battery = psutil.sensors_battery()
    bat_info = {
        "percent": battery.percent if battery else 100,
        "power_plugged": battery.power_plugged if battery else True
    } if battery else {"percent": 100, "power_plugged": True}

    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()

    # Get active window title on Windows
    active_window = "Windows Desktop"
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if win and win.title:
            active_window = win.title[:50]
    except Exception:
        pass

    return {
        "cpu_percent": cpu,
        "ram_percent": ram.percent,
        "ram_used_gb": round(ram.used / (1024 ** 3), 1),
        "ram_total_gb": round(ram.total / (1024 ** 3), 1),
        "battery": bat_info,
        "active_window": active_window,
        "srm_wifi": srm_status,
        "timestamp": time.time()
    }


# ================= HTTP ROUTES =================

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>Laptop Remote Hub Frontend Loading...</h2>")


@app.get("/portal", response_class=HTMLResponse)
async def serve_portal():
    portal_path = os.path.join(WEB_DIR, "portal.html")
    if os.path.exists(portal_path):
        with open(portal_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>24/7 Portal Loading...</h2>")


@app.get("/style.css")
async def serve_css():
    css_path = os.path.join(WEB_DIR, "style.css")
    return FileResponse(css_path, media_type="text/css")


@app.get("/app.js")
async def serve_js():
    js_path = os.path.join(WEB_DIR, "app.js")
    return FileResponse(js_path, media_type="application/javascript")


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "time": time.time()}


@app.get("/api/status")
async def api_status(pin: Optional[str] = None):
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    return get_system_metrics()


@app.get("/api/screenshot")
async def api_screenshot(pin: Optional[str] = None, q: int = 80, scale: float = 0.85):
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    data = capture_screen_jpeg(quality=q, scale=scale)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Screen-Quality": str(q),
            "X-Screen-Scale": str(scale)
        }
    )


@app.websocket("/ws/screen")
async def websocket_screen_stream(websocket: WebSocket):
    """High-frequency binary WebSocket desktop screen streamer (up to 60 FPS)."""
    await websocket.accept()
    authenticated = False
    scale = 0.85
    quality = 80
    target_fps = 30
    is_streaming = True

    try:
        # First message must be auth / config
        init_raw = await websocket.receive_text()
        init_data = json.loads(init_raw)
        if init_data.get("pin") != AUTH_PIN:
            await websocket.send_json({"type": "auth_fail", "error": "Invalid PIN"})
            await websocket.close()
            return

        authenticated = True
        scale = float(init_data.get("scale", 0.85))
        quality = int(init_data.get("quality", 80))
        target_fps = int(init_data.get("fps", 30))
        await websocket.send_json({"type": "stream_ready", "fps": target_fps, "quality": quality, "scale": scale})

        async def incoming_listener():
            nonlocal scale, quality, target_fps, is_streaming
            try:
                while is_streaming:
                    text = await websocket.receive_text()
                    data = json.loads(text)
                    if data.get("type") == "config":
                        scale = float(data.get("scale", scale))
                        quality = int(data.get("quality", quality))
                        target_fps = int(data.get("fps", target_fps))
                    elif data.get("type") == "stop":
                        is_streaming = False
                        break
            except Exception:
                is_streaming = False

        listener_task = asyncio.create_task(incoming_listener())

        loop = asyncio.get_running_loop()
        while is_streaming:
            t_start = time.perf_counter()
            frame_bytes = await loop.run_in_executor(None, capture_screen_jpeg, quality, scale)
            await websocket.send_bytes(frame_bytes)

            elapsed = time.perf_counter() - t_start
            delay = max(0.008, (1.0 / target_fps) - elapsed)
            await asyncio.sleep(delay)

        listener_task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.post("/api/action")
async def api_action(req: Request):
    body = await req.json()
    pin = body.get("pin")
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")

    action = body.get("action")
    
    if action == "vol_up":
        pyautogui.press("volumeup")
    elif action == "vol_down":
        pyautogui.press("volumedown")
    elif action == "vol_mute":
        pyautogui.press("volumemute")
    elif action == "media_play_pause":
        pyautogui.press("playpause")
    elif action == "media_next":
        pyautogui.press("nexttrack")
    elif action == "media_prev":
        pyautogui.press("prevtrack")
    elif action == "lock_screen":
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif action == "sleep_pc":
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    elif action == "restart_pc":
        subprocess.run(["shutdown", "/r", "/t", "5"])
    elif action == "shutdown_pc":
        subprocess.run(["shutdown", "/s", "/t", "10"])
    elif action == "launch_app":
        app_name = body.get("app")
        if app_name == "chrome":
            subprocess.Popen(["cmd", "/c", "start", "chrome"])
        elif app_name == "code":
            subprocess.Popen(["cmd", "/c", "code"])
        elif app_name == "notepad":
            subprocess.Popen(["notepad.exe"])
        elif app_name == "explorer":
            subprocess.Popen(["explorer.exe"])
        elif app_name == "taskmgr":
            subprocess.Popen(["taskmgr.exe"])
        elif app_name == "terminal":
            subprocess.Popen(["wt.exe"])

    return {"status": "ok", "action": action}


INSTALLED_APPS_CACHE = []


def refresh_installed_apps():
    global INSTALLED_APPS_CACHE
    try:
        cmd = ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10)
        data = json.loads(res.stdout)
        if isinstance(data, list):
            INSTALLED_APPS_CACHE = [{"name": item["Name"], "appid": item["AppID"]} for item in data if "Name" in item and "AppID" in item]
            INSTALLED_APPS_CACHE.sort(key=lambda x: x["name"].lower())
    except Exception as e:
        print(f"Error loading installed apps: {e}")


@app.get("/api/apps")
async def get_apps(q: Optional[str] = None, pin: Optional[str] = None):
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    if not INSTALLED_APPS_CACHE:
        refresh_installed_apps()
        
    if q:
        query = q.lower()
        filtered = [app for app in INSTALLED_APPS_CACHE if query in app["name"].lower()]
        return {"apps": filtered}
    return {"apps": INSTALLED_APPS_CACHE}


@app.post("/api/apps/launch")
async def launch_app_endpoint(req: Request):
    body = await req.json()
    if body.get("pin") != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")

    appid = body.get("appid")
    name = body.get("name")
    
    if appid:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"])
    elif name:
        subprocess.Popen(["cmd", "/c", "start", "", name])
    return {"status": "ok", "launched": appid or name}


@app.get("/api/files")
async def list_files(path: Optional[str] = None, pin: Optional[str] = None):
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    
    try:
        resolved_path = os.path.abspath(path if path else os.environ.get("USERPROFILE", "C:\\"))
        if not os.path.exists(resolved_path):
            return JSONResponse({"error": "Path not found"}, status_code=404)

        items = []
        # Add parent directory entry
        parent = os.path.dirname(resolved_path)
        if parent and parent != resolved_path:
            items.append({"name": "..", "path": parent, "is_dir": True, "size": 0})

        with os.scandir(resolved_path) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                    size = 0 if is_dir else entry.stat().st_size
                    items.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": is_dir,
                        "size": size,
                        "modified": entry.stat().st_mtime
                    })
                except PermissionError:
                    continue

        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return {"current_path": resolved_path, "items": items}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/files/download")
async def download_file(path: str, pin: Optional[str] = None):
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    if os.path.isfile(path):
        return FileResponse(path, filename=os.path.basename(path))
    raise HTTPException(status_code=404, detail="File not found")


@app.post("/api/files/upload")
async def upload_file(pin: str = Form(...), dest_dir: str = Form(...), file: UploadFile = File(...)):
    if pin != AUTH_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    try:
        dest_path = os.path.join(dest_dir, file.filename)
        with open(dest_path, "wb") as f:
            f.write(await file.read())
        return {"status": "ok", "filename": file.filename, "path": dest_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================= WEBSOCKET REAL-TIME CONTROLLER =================

@app.websocket("/ws")
async def websocket_controller(websocket: WebSocket):
    await websocket.accept()
    authenticated = False
    screen_width, screen_height = get_screen_dimensions()

    try:
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            msg_type = data.get("type")

            # Authentication check
            if not authenticated:
                if msg_type == "auth" and data.get("pin") == AUTH_PIN:
                    authenticated = True
                    await websocket.send_json({
                        "type": "auth_ok",
                        "screen_w": screen_width,
                        "screen_h": screen_height
                    })
                    continue
                else:
                    await websocket.send_json({"type": "auth_fail", "error": "Invalid PIN"})
                    await websocket.close()
                    break

            # Handle mouse movements
            if msg_type == "mouse_move":
                dx = data.get("dx", 0)
                dy = data.get("dy", 0)
                # Apply smooth non-linear acceleration
                speed = data.get("speed", 1.2)
                pyautogui.moveRel(dx * speed, dy * speed)

            # Handle mouse clicks
            elif msg_type == "mouse_click":
                btn = data.get("button", "left")
                clicks = data.get("clicks", 1)
                pyautogui.click(button=btn, clicks=clicks)

            elif msg_type == "mouse_down":
                btn = data.get("button", "left")
                pyautogui.mouseDown(button=btn)

            elif msg_type == "mouse_up":
                btn = data.get("button", "left")
                pyautogui.mouseUp(button=btn)

            elif msg_type == "mouse_scroll":
                dy = data.get("dy", 0)
                pyautogui.scroll(int(-dy * 25))

            # Tap on specific screen coordinate from phone screen viewer
            elif msg_type == "screen_click":
                x_pct = data.get("x_pct", 0)
                y_pct = data.get("y_pct", 0)
                btn = data.get("button", "left")
                clicks = data.get("clicks", 1)
                abs_x = int(x_pct * screen_width)
                abs_y = int(y_pct * screen_height)
                pyautogui.click(x=abs_x, y=abs_y, button=btn, clicks=clicks)

            # Handle Keyboard & Live Typing
            elif msg_type == "key_press":
                key = data.get("key", "").lower()
                if key:
                    try:
                        pyautogui.press(key)
                    except Exception as e:
                        print(f"Key press error {key}: {e}")

            elif msg_type == "key_down":
                key = data.get("key", "").lower()
                if key:
                    pyautogui.keyDown(key)

            elif msg_type == "key_up":
                key = data.get("key", "").lower()
                if key:
                    pyautogui.keyUp(key)

            elif msg_type == "type_text":
                text = data.get("text", "")
                mode = data.get("mode", "type")
                if text:
                    try:
                        import pyperclip
                        if mode == "paste" or any(ord(c) > 127 for c in text) or "\n" in text:
                            # Use clipboard paste for instant & Unicode/Emoji support
                            pyperclip.copy(text)
                            pyautogui.hotkey("ctrl", "v")
                        else:
                            pyautogui.write(text, interval=0.001)
                    except Exception:
                        pyautogui.write(text, interval=0.001)

            elif msg_type == "hotkey":
                keys = data.get("keys", [])
                if keys:
                    try:
                        pyautogui.hotkey(*[k.lower() for k in keys])
                    except Exception as e:
                        print(f"Hotkey error {keys}: {e}")

            # Handle Clipboard Sync
            elif msg_type == "get_clipboard":
                try:
                    import pyperclip
                    clip_text = pyperclip.paste()
                    await websocket.send_json({"type": "clipboard_data", "text": clip_text})
                except Exception as e:
                    await websocket.send_json({"type": "clipboard_data", "text": ""})

            elif msg_type == "set_clipboard":
                try:
                    import pyperclip
                    pyperclip.copy(data.get("text", ""))
                    await websocket.send_json({"type": "clipboard_set_ok"})
                except Exception:
                    pass

            # Handle Terminal Execution
            elif msg_type == "terminal_exec":
                command = data.get("command", "")
                cmd_id = data.get("cmd_id", "0")
                asyncio.create_task(run_terminal_command(websocket, command, cmd_id))

            # Handle System Status Request
            elif msg_type == "get_stats":
                metrics = get_system_metrics()
                await websocket.send_json({"type": "stats", "data": metrics})

            # Handle WebSocket Heartbeat Ping
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "time": time.time()})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[!] WebSocket exception: {e}")


async def run_terminal_command(websocket: WebSocket, cmd: str, cmd_id: str):
    """Runs a PowerShell command and streams stdout/stderr in real-time."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe", "-NoProfile", "-Command", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        async def read_stream(stream, stream_name):
            while True:
                line = await stream.readline()
                if not line:
                    break
                await websocket.send_json({
                    "type": "terminal_output",
                    "cmd_id": cmd_id,
                    "stream": stream_name,
                    "text": line.decode("utf-8", errors="replace")
                })

        await asyncio.gather(
            read_stream(proc.stdout, "stdout"),
            read_stream(proc.stderr, "stderr")
        )
        
        exit_code = await proc.wait()
        await websocket.send_json({
            "type": "terminal_done",
            "cmd_id": cmd_id,
            "exit_code": exit_code
        })
    except Exception as e:
        await websocket.send_json({
            "type": "terminal_output",
            "cmd_id": cmd_id,
            "stream": "stderr",
            "text": f"Error: {str(e)}\n"
        })


def run_hub(port=8765, pin="1234"):
    global AUTH_PIN
    AUTH_PIN = pin

    # Start SRM Sentinel in background thread
    start_sentinel_thread()

    # Start Cloudflare Global Tunnel
    tunnel = Tunnel(port=port, pin=pin)
    tunnel_thread = threading.Thread(target=tunnel.start, daemon=True)
    tunnel_thread.start()

    print("\n" + "=" * 60)
    print("  LAPTOP REMOTE HUB STARTED")
    print(f"  Local Access: http://localhost:{port}?pin={pin}")
    print(f"  Security PIN: {pin}")
    print("=" * 60 + "\n")

    try:
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=port,
            log_level="warning",
            access_log=False
        )
        srv = uvicorn.Server(config)
        srv.run()
    except Exception as e:
        import traceback
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[Server Fatal Error] {e}\n")
            traceback.print_exc(file=f)


if __name__ == "__main__":
    run_hub()
