"""
24/7 Central Portal Beacon & Cloud Registry Synchronizer
-------------------------------------------------------
Automatically broadcasts the laptop's live public/local tunnel URL, PIN, device name,
battery status, and resolution to a permanent 24/7 Cloud Registry Channel.

This allows the user to open ONE permanent bookmarked website on their phone
and immediately see active online laptops with a 1-tap Direct Connect / Mirror button,
without EVER having to copy-paste links again!
"""

import os
import sys
import json
import time
import socket
import urllib.request
import threading
import psutil
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONNECTION_INFO_FILE = os.path.join(BASE_DIR, "connection_info.json")

logger = logging.getLogger("PortalBeacon")

# Default registry topic that links the phone portal to all your computers
DEFAULT_PORTAL_CHANNEL = "praashu-remote-portal-247"


def get_portal_channel():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return cfg.get("portal_channel") or cfg.get("ntfy_topic") or DEFAULT_PORTAL_CHANNEL
        except Exception:
            pass
    return DEFAULT_PORTAL_CHANNEL


def get_device_info():
    hostname = socket.gethostname()
    username = os.environ.get("USERNAME", "User")
    device_name = f"{username} ({hostname})"

    try:
        from screen_capturer import get_screen_size
        w, h = get_screen_size()
        resolution = f"{w}x{h}"
    except Exception:
        resolution = "1920x1080"

    battery = psutil.sensors_battery()
    bat_pct = battery.percent if battery else 100
    plugged = battery.power_plugged if battery else True
    cpu = psutil.cpu_percent(interval=None)

    return {
        "device_id": f"{hostname.lower()}-{username.lower()}",
        "device_name": device_name,
        "resolution": resolution,
        "battery_pct": bat_pct,
        "power_plugged": plugged,
        "cpu_pct": cpu
    }


def broadcast_beacon(public_url: str, local_url: str, pin: str = "1234"):
    """Publishes live connection credentials & health status to 24/7 Cloud Registry."""
    if not public_url and not local_url:
        return

    # Filter out dummy/mock test URLs
    if public_url and ("test-tunnel" in public_url or "example.com" in public_url):
        return

    channel = get_portal_channel()
    dev = get_device_info()

    target_clean = public_url or local_url
    if target_clean:
        if "?pin=" not in target_clean:
            target_clean = f"{target_clean}?pin={pin}"
    else:
        target_clean = ""

    payload = {
        "event": "hub_beacon",
        "device_id": dev["device_id"],
        "device_name": dev["device_name"],
        "public_url": public_url,
        "local_url": local_url,
        "pin": pin,
        "resolution": dev["resolution"],
        "battery": f"{dev['battery_pct']}%",
        "power_plugged": dev["power_plugged"],
        "cpu": f"{dev['cpu_pct']}%",
        "status": "ready" if public_url else "lan_only",
        "timestamp": int(time.time()),
        "connect_url": target_clean
    }

    # 1. Broadcast to ntfy.sh channel with JSON message
    try:
        ntfy_url = f"https://ntfy.sh/{channel}"
        data_bytes = json.dumps(payload).encode("utf-8")
        safe_title = f"{dev['device_name']} Online".encode("ascii", "ignore").decode("ascii").strip()
        req = urllib.request.Request(
            ntfy_url,
            data=data_bytes,
            headers={
                "Title": safe_title or "Laptop Online",
                "Tags": "computer,satellite,link",
                "User-Agent": "LaptopRemoteHub-Beacon/2.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                logger.info(f"Broadcasted live beacon to 24/7 Portal Channel: '{channel}'")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            logger.info("Beacon broadcast throttled (429) - backing off for 60s")
            time.sleep(30)
        else:
            logger.warning(f"Beacon broadcast warning: {e}")
    except Exception as e:
        logger.warning(f"Beacon broadcast warning: {e}")

    # 2. Also save locally in connection_info.json
    try:
        with open(CONNECTION_INFO_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


_beacon_thread = None
_beacon_active = False


def _beacon_loop(public_url_func, local_url_func, pin_func):
    global _beacon_active
    last_pub = ""
    while _beacon_active:
        try:
            pub_url = public_url_func() if callable(public_url_func) else public_url_func
            loc_url = local_url_func() if callable(local_url_func) else local_url_func
            p = pin_func() if callable(pin_func) else pin_func
            if pub_url or loc_url:
                broadcast_beacon(pub_url, loc_url, p)
                last_pub = pub_url
        except Exception as e:
            logger.debug(f"Beacon loop error: {e}")
        time.sleep(55)  # 55-second heartbeat prevents rate limits


def start_portal_beacon_thread(get_public_url, get_local_url, get_pin):
    global _beacon_thread, _beacon_active
    _beacon_active = True
    _beacon_thread = threading.Thread(
        target=_beacon_loop,
        args=(get_public_url, get_local_url, get_pin),
        daemon=True,
        name="PortalBeaconThread"
    )
    _beacon_thread.start()
    return _beacon_thread


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    print("Portal Beacon module ready.")
