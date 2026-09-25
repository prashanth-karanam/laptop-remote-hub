"""
Phone Notifier & Ping Listener for Laptop Remote Hub
-----------------------------------------------------
1. Automatically sends mobile push notifications when PC reboots or tunnel reconnects.
2. Listens for incoming 'ping' or 'link' triggers from your phone and replies with the live URL.
3. Completely free, requires no login, no accounts, and works globally via ntfy.sh.
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

logger = logging.getLogger("PhoneNotifier")

_uname = os.environ.get("USERNAME", "laptop").lower().replace(" ", "-")
DEFAULT_TOPIC = f"{_uname}-remote"


def get_config():
    """Loads configuration from config.json."""
    cfg = {"ntfy_topic": DEFAULT_TOPIC, "telegram_token": "", "telegram_chat_id": ""}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception:
            pass
    return cfg


def get_system_summary():
    """Gets human-readable battery and load metrics."""
    try:
        battery = psutil.sensors_battery()
        if battery:
            plugged = "Plugged In" if battery.power_plugged else "On Battery"
            bat_str = f"{battery.percent}% ({plugged})"
        else:
            bat_str = "100% (Plugged In)"
    except Exception:
        bat_str = "N/A"

    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        sys_str = f"CPU: {cpu}% | RAM: {ram}%"
    except Exception:
        sys_str = ""

    return bat_str, sys_str


def get_active_link():
    """Reads the current active link from connection_info.json."""
    if os.path.exists(CONNECTION_INFO_FILE):
        try:
            with open(CONNECTION_INFO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("url") or data.get("public_url") or data.get("local_url"), data.get("pin", "1234")
        except Exception:
            pass
    return None, "1234"


def send_mobile_notification(url: str, pin: str = "1234", title: str = "Laptop Online & Ready 24/7"):
    """Sends push notification to phone via ntfy.sh."""
    cfg = get_config()
    topic = cfg.get("ntfy_topic", DEFAULT_TOPIC)
    bat_str, sys_str = get_system_summary()

    body = (
        f"Link: {url}\n"
        f"PIN: {pin}\n"
        f"Battery: {bat_str}\n"
        f"Status: {sys_str}\n"
        f"Tap this notification to connect directly!"
    )

    # 1. Send via ntfy.sh
    try:
        url_target = f"https://ntfy.sh/{topic}"
        # Ensure HTTP header title is ASCII-safe
        safe_title = title.encode("ascii", "ignore").decode("ascii").strip()
        if not safe_title:
            safe_title = "Laptop Online & Ready 24/7"
        req = urllib.request.Request(
            url_target,
            data=body.encode("utf-8"),
            headers={
                "Title": safe_title,
                "Priority": "high",
                "Tags": "computer,link,rocket",
                "Click": url,
                "User-Agent": "LaptopRemoteHub/2.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                logger.info(f"Successfully pushed notification to phone topic: {topic}")
    except Exception as e:
        logger.warning(f"Failed to send ntfy push notification: {e}")

    # 2. Optional Telegram Bot notification if configured
    tg_token = cfg.get("telegram_token")
    tg_chat = cfg.get("telegram_chat_id")
    if tg_token and tg_chat:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            tg_msg = f"*{title}*\n\n[Connect Here]({url})\nPIN: `{pin}`\nBattery: {bat_str}\n{sys_str}"
            payload = json.dumps({"chat_id": tg_chat, "text": tg_msg, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(
                tg_url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "LaptopRemoteHub/2.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                pass
        except Exception as e:
            logger.warning(f"Telegram notification note: {e}")


def _ping_listener_worker():
    """Background listener that polls for phone pings with zero socket deadlocks."""
    cfg = get_config()
    topic = cfg.get("ntfy_topic", DEFAULT_TOPIC)
    last_check_time = int(time.time())

    logger.info(f"Phone ping listener active on topic: {topic}")

    while True:
        try:
            time.sleep(3)
            poll_url = f"https://ntfy.sh/{topic}/json?poll=1&since={last_check_time}"
            req = urllib.request.Request(poll_url, headers={"User-Agent": "LaptopRemoteHub-Listener/2.0"})
            
            with urllib.request.urlopen(req, timeout=6) as resp:
                lines = [line.decode("utf-8").strip() for line in resp if line.strip()]

            for line in lines:
                try:
                    event = json.loads(line)
                    event_time = event.get("time", 0)
                    if event_time > last_check_time:
                        last_check_time = event_time

                    if event.get("event") != "message":
                        continue

                    msg = event.get("message", "")
                    # Ignore messages originated by our own laptop
                    if msg.startswith("Link:") or "Tap this notification to connect" in msg:
                        continue

                    # If user pinged the topic
                    trigger_words = ["ping", "link", "url", "where", "connect", "status", "hey", "open", "help"]
                    if any(w in msg.lower() for w in trigger_words) or len(msg.strip()) < 15:
                        logger.info(f"Received phone ping: '{msg}'. Sending live link back...")
                        url, pin = get_active_link()
                        if url:
                            send_mobile_notification(
                                url=url,
                                pin=pin,
                                title="🔔 Ping Received! Here is your Laptop Link"
                            )
                except Exception:
                    pass

        except Exception as e:
            time.sleep(4)


def start_ping_listener():
    """Launches the background ping listener thread."""
    t = threading.Thread(target=_ping_listener_worker, daemon=True, name="PhonePingListener")
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    test_url = "https://example.com"
    print("Testing phone notification...")
    send_mobile_notification(test_url, "1234", "Test Notification from Antigravity")
