"""
Immortal Supervisor & Auto-Revival Daemon for Laptop Remote Hub
---------------------------------------------------------------
1. Keeps Server, Multi-Layer Tunnel, and SRM Sentinel running 24/7.
2. Actively probes local server health and auto-revives if hung or crashed.
3. Holds Kernel Sleep Lock continuously.
4. Keeps desktop shortcut 'OPEN_PHONE_REMOTE.url' synchronized with the latest active link.
"""

import os
import sys
import time
import subprocess
import urllib.request
import ctypes
import json
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "hub_supervisor.log")

if sys.stdout is None or not hasattr(sys.stdout, "write"):
    sys.stdout = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
if sys.stderr is None or not hasattr(sys.stderr, "write"):
    sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

def get_desktop_dir():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
            desktop = os.path.expandvars(desktop)
            if os.path.isdir(desktop):
                return desktop
    except Exception:
        pass
    onedrive = os.environ.get("OneDrive", "")
    if onedrive and os.path.isdir(os.path.join(onedrive, "Desktop")):
        return os.path.join(onedrive, "Desktop")
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile and os.path.isdir(os.path.join(userprofile, "Desktop")):
        return os.path.join(userprofile, "Desktop")
    return os.path.expanduser("~/Desktop")

DESKTOP_DIR = get_desktop_dir()
STATUS_FILE = os.path.join(BASE_DIR, "connection_info.json")

# Windows Power Management Flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [Supervisor] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Supervisor")


def hold_kernel_power_lock():
    """Continuously ensures Windows never sleeps CPU or Wi-Fi while running."""
    try:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            )
    except Exception:
        pass


def kill_stale_processes():
    """Cleans up orphan cloudflared or python processes listening on port 8765."""
    try:
        res = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=5
        )
        for line in res.stdout.splitlines():
            if ":8765" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid and pid != str(os.getpid()):
                    logger.info(f"Terminating stale process on port 8765 (PID {pid})...")
                    subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, timeout=5)
    except Exception as e:
        logger.debug(f"Stale process cleanup note: {e}")


def update_desktop_shortcut(url):
    """Creates a clickable Windows Internet shortcut on Desktop with the latest URL."""
    try:
        shortcut_path = os.path.join(DESKTOP_DIR, "OPEN_PHONE_REMOTE.url")
        content = f"[InternetShortcut]\nURL={url}\nIconIndex=0\nIconFile=C:\\Windows\\System32\\shell32.dll\n"
        with open(shortcut_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        logger.warning(f"Could not update desktop shortcut: {e}")


def is_server_healthy(port=8765):
    """Checks if server.py is actively responding to HTTP requests."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"User-Agent": "SupervisorHealth/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.getcode() == 200
    except Exception:
        return False


PYTHON_EXE = sys.executable
if "pythonw" in PYTHON_EXE.lower():
    py_candidate = PYTHON_EXE.lower().replace("pythonw.exe", "python.exe")
    if os.path.exists(py_candidate):
        PYTHON_EXE = py_candidate

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def supervisor_loop():
    logger.info("Immortal Supervisor started. Guarding Laptop Remote Hub & SRM Sentinel 24/7...")
    
    # Start phone ping listener daemon
    try:
        from phone_notifier import start_ping_listener
        start_ping_listener()
        logger.info("Phone ping listener registered successfully.")
    except Exception as ple:
        logger.warning(f"Could not start ping listener: {ple}")

    server_process = None
    failed_health_checks = 0

    while True:
        try:
            hold_kernel_power_lock()

            # Check if server process is dead
            if server_process is None or server_process.poll() is not None:
                logger.warning("Server process not running. Cleaning stale ports and launching server.py...")
                kill_stale_processes()
                time.sleep(1)
                server_log = open(os.path.join(BASE_DIR, "hub_server.log"), "a", encoding="utf-8")
                server_process = subprocess.Popen(
                    [PYTHON_EXE, os.path.join(BASE_DIR, "server.py")],
                    cwd=BASE_DIR,
                    stdout=server_log,
                    stderr=server_log,
                    creationflags=CREATE_NO_WINDOW
                )
                failed_health_checks = 0
                
                # Initial startup grace period (wait up to 25s for server.py to listen)
                for _ in range(25):
                    time.sleep(1)
                    if is_server_healthy(8765):
                        logger.info("Server is up and responding on port 8765.")
                        break
            else:
                # Active HTTP Health Check to detect frozen / unresponsive server
                if not is_server_healthy(8765):
                    failed_health_checks += 1
                    if failed_health_checks >= 6:
                        logger.error("Server is unresponsive for 6 consecutive checks (30s). Restarting server...")
                        try:
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(server_process.pid)], capture_output=True, timeout=5)
                        except Exception:
                            pass
                        server_process = None
                        failed_health_checks = 0
                else:
                    failed_health_checks = 0

            # Check connection_info.json and keep desktop shortcut synchronized
            if os.path.exists(STATUS_FILE):
                try:
                    with open(STATUS_FILE, "r", encoding="utf-8") as f:
                        info = json.load(f)
                    url = info.get("url")
                    if url:
                        update_desktop_shortcut(url)
                except Exception:
                    pass

        except Exception as err:
            logger.error(f"Unexpected supervisor error (auto-recovering): {err}", exc_info=True)

        time.sleep(5)


if __name__ == "__main__":
    while True:
        try:
            supervisor_loop()
        except Exception as e:
            logger.critical(f"Supervisor loop exited with error: {e}. Restarting in 5s...", exc_info=True)
            time.sleep(5)

