"""
SRMIST Wi-Fi Sentinel & Keep-Alive Daemon
-----------------------------------------
Maintains 24/7 continuous connectivity on SRMIST campus network:
1. Prevents idle timeouts and gateway session drops via periodic lightweight keepalives.
2. Automatically detects connection drops and forces auto-reconnection to 'SRMIST'.
3. Locks Windows Power Execution State to prevent laptop & Wi-Fi adapter from sleeping.
"""

import os
import sys
import time
import socket
import urllib.request
import subprocess
import ctypes
import threading
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "hub_sentinel.log")

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

sys.stdout = make_stream_safe(sys.stdout, LOG_FILE)
sys.stderr = make_stream_safe(sys.stderr, LOG_FILE)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [SRM-Sentinel] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SRMSentinel")

# Windows Power Management Flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040

TARGET_SSID = "SRMIST"
KEEPALIVE_INTERVAL = 8  # seconds between heartbeat requests
PROBE_URLS = [
    "http://connectivitycheck.gstatic.com/generate_204",
    "http://www.msftconnecttest.com/connecttest.txt",
    "http://1.1.1.1",
    "http://detectportal.firefox.com/success.txt"
]

status_data = {
    "connected": True,
    "last_ping_time": "",
    "latency_ms": 0,
    "ssid": TARGET_SSID,
    "reconnect_count": 0,
    "active": True
}


def prevent_windows_sleep():
    """Instructs Windows Kernel to never sleep CPU or Wi-Fi while running."""
    try:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            )
            logger.info("Windows Power Lock active: Sleep & Wi-Fi power-save prevented.")
    except Exception as e:
        logger.warning(f"Could not set thread execution state: {e}")


def get_current_wifi_ssid():
    """Queries netsh for current active Wi-Fi SSID."""
    try:
        res = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("SSID") and not line.startswith("SSID name"):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
            elif line.startswith("State"):
                parts = line.split(":", 1)
                if len(parts) > 1 and "disconnected" in parts[1].lower():
                    return None
    except Exception:
        pass
    return None


def force_reconnect(ssid=TARGET_SSID):
    """Forces Windows to connect to target Wi-Fi SSID."""
    logger.warning(f"Attempting to reconnect to '{ssid}'...")
    try:
        res = subprocess.run(
            ["netsh", "wlan", "connect", f"name={ssid}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        logger.info(f"netsh output: {res.stdout.strip()}")
        status_data["reconnect_count"] += 1
        time.sleep(3)
    except Exception as e:
        logger.error(f"Failed to execute netsh reconnect: {e}")


def check_internet_connectivity():
    """Sends lightweight heartbeat requests and verifies internet reachability vs captive portal."""
    # 1. Probe generate_204
    try:
        start = time.perf_counter()
        req = urllib.request.Request(
            "http://connectivitycheck.gstatic.com/generate_204",
            headers={"User-Agent": "SRM-KeepAlive/2.0", "Cache-Control": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            latency = round((time.perf_counter() - start) * 1000, 1)
            # True internet returns HTTP 204 with no content
            if resp.getcode() == 204:
                return True, latency
            # If redirected to captive portal (HTTP 200/302 with login page)
            if resp.getcode() == 200:
                body = resp.read(512).decode("utf-8", errors="ignore").lower()
                if "login" in body or "portal" in body or "authenticate" in body:
                    logger.warning("Captive portal intercepted internet traffic! Re-authentication may be needed.")
                    return False, latency
    except Exception:
        pass

    # 2. Probe Microsoft Connect Test
    try:
        start = time.perf_counter()
        req = urllib.request.Request(
            "http://www.msftconnecttest.com/connecttest.txt",
            headers={"User-Agent": "SRM-KeepAlive/2.0", "Cache-Control": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            text = resp.read().decode("utf-8", errors="ignore").strip()
            if "Microsoft Connect Test" in text:
                latency = round((time.perf_counter() - start) * 1000, 1)
                return True, latency
    except Exception:
        pass
            
    # 3. Try raw socket DNS ping as fallback
    try:
        start = time.perf_counter()
        socket.setdefaulttimeout(3)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
        s.close()
        latency = round((time.perf_counter() - start) * 1000, 1)
        return True, latency
    except Exception:
        return False, 0


def sentinel_loop(callback=None):
    """Main keepalive watchdog loop."""
    prevent_windows_sleep()
    logger.info(f"Sentinel started. Monitoring Wi-Fi and holding active state for '{TARGET_SSID}'...")

    consecutive_failures = 0

    while status_data["active"]:
        connected, latency = check_internet_connectivity()
        current_ssid = get_current_wifi_ssid()
        
        status_data["connected"] = connected
        status_data["latency_ms"] = latency
        status_data["ssid"] = current_ssid or "Disconnected"
        status_data["last_ping_time"] = datetime.now().strftime("%H:%M:%S")

        if connected:
            consecutive_failures = 0
            logger.info(f"Heartbeat OK | SSID: {current_ssid} | Latency: {latency}ms")
        else:
            consecutive_failures += 1
            logger.warning(f"Heartbeat FAILED ({consecutive_failures}) | SSID: {current_ssid}")
            
            if consecutive_failures >= 2:
                force_reconnect(TARGET_SSID)
                consecutive_failures = 0

        # Periodic refresh of Windows power lock
        prevent_windows_sleep()

        if callback:
            try:
                callback(status_data)
            except Exception:
                pass

        time.sleep(KEEPALIVE_INTERVAL)


def start_sentinel_thread():
    """Runs sentinel loop in a daemon background thread."""
    t = threading.Thread(target=sentinel_loop, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    print("=" * 60)
    print("  SRMIST Wi-Fi Sentinel & Keep-Alive Service")
    print(f"  Target Network: {TARGET_SSID}")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    try:
        sentinel_loop()
    except KeyboardInterrupt:
        print("\nStopping sentinel...")
