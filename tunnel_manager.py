"""
Ultra-Resilient Multi-Layer Tunnel Manager with Zero Pipe-Buffer Deadlocks
--------------------------------------------------------------------------
1. Establishes global HTTPS tunnel via Cloudflare with continuous background pipe draining.
2. Supports persistent Named Cloudflare Tunnel tokens (via config.json) for static URLs.
3. Automatically falls back to high-resilience Quick Tunnel (trycloudflare.com).
4. Provides Local Network (LAN) fallback URL for guaranteed offline/same-network connectivity.
5. Watchdog with clean process-tree auto-healing.
"""

import os
import sys
import time
import socket
import subprocess
import urllib.request
import re
import threading
import json
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "hub_tunnel.log")

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
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONNECTION_INFO_FILE = os.path.join(BASE_DIR, "connection_info.json")
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
LOCAL_CLOUDFLARED_PATH = os.path.join(BASE_DIR, "cloudflared.exe")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [TunnelManager] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TunnelManager")


def get_local_ip():
    """Gets the active local Wi-Fi / Ethernet IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_custom_config():
    """Loads optional custom tunnel token and domain configuration."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read config.json: {e}")
    return {}


def ensure_cloudflared():
    if os.path.exists(LOCAL_CLOUDFLARED_PATH):
        return LOCAL_CLOUDFLARED_PATH

    try:
        res = subprocess.run(["where", "cloudflared"], capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.strip().splitlines()[0]
    except Exception:
        pass

    logger.info("Downloading cloudflared.exe...")
    try:
        req = urllib.request.Request(CLOUDFLARED_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(LOCAL_CLOUDFLARED_PATH, "wb") as f:
            f.write(resp.read())
        return LOCAL_CLOUDFLARED_PATH
    except Exception as e:
        logger.error(f"Failed to download cloudflared: {e}")
        return None


def update_shortcuts_and_qr(public_url, local_url, pin):
    try:
        info = {
            "url": public_url or local_url,
            "public_url": public_url,
            "local_url": local_url,
            "pin": pin,
            "timestamp": time.time()
        }
        with open(CONNECTION_INFO_FILE, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)

        best_url = public_url if public_url else local_url
        if best_url:
            # Update desktop shortcut
            shortcut_path = os.path.join(DESKTOP_DIR, "OPEN_PHONE_REMOTE.url")
            content = f"[InternetShortcut]\nURL={best_url}\nIconIndex=0\nIconFile=C:\\Windows\\System32\\shell32.dll\n"
            with open(shortcut_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Update QR image
            try:
                import qrcode
                qr = qrcode.QRCode(box_size=10, border=2)
                qr.add_data(best_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#00d2ff", back_color="#0a0e17")
                img.save(os.path.join(BASE_DIR, "remote_qr.png"))
            except Exception as qre:
                logger.warning(f"QR code generation note: {qre}")

            # Send mobile push notification with click-to-connect URL
            try:
                from phone_notifier import send_mobile_notification
                send_mobile_notification(best_url, pin, "💻 Laptop Online & Ready 24/7")
            except Exception as pe:
                logger.warning(f"Mobile push notification note: {pe}")

            # Broadcast to 24/7 Central Web Portal Cloud Registry
            try:
                from portal_beacon import broadcast_beacon
                broadcast_beacon(public_url, local_url, pin)
            except Exception as pbe:
                logger.warning(f"Portal beacon note: {pbe}")
    except Exception as e:
        logger.warning(f"Error updating shortcuts: {e}")


class ResilientTunnel:
    def __init__(self, port=8765, pin="1234"):
        self.port = port
        self.pin = pin
        self.public_url = None
        self.local_url = f"http://{get_local_ip()}:{self.port}?pin={self.pin}"
        self.process = None
        self.is_running = True
        self._url_event = threading.Event()
        self._reader_thread = None

    def _pipe_drainer(self, proc):
        """Continuously reads lines from cloudflared stdout/stderr to prevent OS pipe buffer deadlocks."""
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                line_str = line.strip()
                
                # Parse trycloudflare URL
                if not self.public_url and "trycloudflare.com" in line_str:
                    matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line_str)
                    for m in matches:
                        if "api.trycloudflare.com" not in m:
                            self.public_url = f"{m}?pin={self.pin}"
                            logger.info(f"Assigned Tunnel URL: {self.public_url}")
                            self._url_event.set()
                            update_shortcuts_and_qr(self.public_url, self.local_url, self.pin)
                            break
                elif "Registered tunnel connection" in line_str:
                    self._url_event.set()

                # Log important lines without spamming
                if "ERR" in line_str or "error" in line_str.lower():
                    logger.warning(f"[Cloudflare] {line_str}")
                elif "Retrying connection" in line_str:
                    logger.info(f"[Cloudflare] {line_str}")
        except Exception as e:
            logger.debug(f"Pipe drainer closed: {e}")

    def _kill_proc_tree(self):
        """Cleanly terminates cloudflared and its child process tree."""
        if self.process:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    capture_output=True,
                    timeout=5
                )
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _spawn_tunnel(self):
        self._kill_proc_tree()
        self._url_event.clear()
        self.public_url = None

        binary = ensure_cloudflared()
        if not binary:
            logger.error("Cloudflared binary not available. Operating in LAN-only mode.")
            update_shortcuts_and_qr(None, self.local_url, self.pin)
            return None

        cfg = load_custom_config()
        token = cfg.get("cloudflare_token") or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN")
        custom_domain = cfg.get("custom_domain")

        if token:
            logger.info("Spawning persistent Cloudflare Named Tunnel via Token...")
            cmd = [
                binary, "tunnel", "run",
                "--token", token,
                "--no-autoupdate",
                "--protocol", "auto",
                "--heartbeat-count", "5",
                "--heartbeat-interval", "5s"
            ]
            if custom_domain:
                self.public_url = f"https://{custom_domain}?pin={self.pin}"
        else:
            logger.info("Spawning Cloudflare Global Quick Tunnel with auto keep-alives...")
            cmd = [
                binary, "tunnel",
                "--url", f"http://127.0.0.1:{self.port}",
                "--no-autoupdate",
                "--protocol", "auto",
                "--edge-ip-version", "auto",
                "--heartbeat-count", "5",
                "--heartbeat-interval", "5s",
                "--retries", "10"
            ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1
            )
        except Exception as e:
            logger.error(f"Failed to start cloudflared process: {e}")
            return None

        # Start continuous stdout drainer thread immediately
        self._reader_thread = threading.Thread(
            target=self._pipe_drainer,
            args=(self.process,),
            daemon=True
        )
        self._reader_thread.start()

        if token and custom_domain:
            self._url_event.set()
        else:
            # Wait up to 35 seconds for tunnel registration
            self._url_event.wait(timeout=35)

        self.local_url = f"http://{get_local_ip()}:{self.port}?pin={self.pin}"
        update_shortcuts_and_qr(self.public_url, self.local_url, self.pin)

        print("\n" + "=" * 62, flush=True)
        print("  LAPTOP REMOTE HUB - NETWORK CHANNELS READY", flush=True)
        print("-" * 62, flush=True)
        if self.public_url:
            print(f"  [GLOBAL HTTPS] : {self.public_url}", flush=True)
        print(f"  [LOCAL WI-FI]  : {self.local_url}", flush=True)
        print("=" * 62 + "\n", flush=True)

        return self.public_url

    def _health_check_loop(self):
        """Active health watchdog that probes tunnel and auto-heals only when needed."""
        consecutive_errors = 0

        while self.is_running:
            time.sleep(20)
            if not self.is_running:
                break

            # 1. First probe local server to verify FastAPI is alive
            try:
                local_probe = f"http://127.0.0.1:{self.port}/api/health"
                req_local = urllib.request.Request(local_probe, headers={"User-Agent": "Watchdog/1.0"})
                with urllib.request.urlopen(req_local, timeout=5) as resp:
                    if resp.getcode() != 200:
                        continue
            except Exception:
                # Local server starting or busy; skip tunnel probe
                continue

            # 2. Check public tunnel if available
            if not self.public_url:
                consecutive_errors += 1
                if consecutive_errors >= 2:
                    logger.warning("No public tunnel active. Attempting revival...")
                    self._spawn_tunnel()
                    consecutive_errors = 0
                continue

            try:
                probe_url = f"{self.public_url.split('?')[0]}/api/health"
                req = urllib.request.Request(probe_url, headers={"User-Agent": "TunnelWatchdog/2.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.getcode() == 200:
                        consecutive_errors = 0
                        continue
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"Tunnel probe warning ({consecutive_errors}/3): {e}")

            # Auto-heal only after 3 consecutive failures (approx 60-70s of dropped connection)
            if consecutive_errors >= 3:
                logger.error("Cloudflare tunnel dropped! Auto-healing & spawning fresh tunnel...")
                self._spawn_tunnel()
                consecutive_errors = 0

    def start(self):
        self._spawn_tunnel()
        health_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        health_thread.start()

        # Start continuous 24/7 Cloud Registry Beacon loop
        try:
            from portal_beacon import start_portal_beacon_thread
            start_portal_beacon_thread(
                get_public_url=lambda: self.public_url,
                get_local_url=lambda: self.local_url,
                get_pin=lambda: self.pin
            )
        except Exception as e:
            logger.warning(f"Failed to start portal beacon thread: {e}")

    def stop(self):
        self.is_running = False
        self._kill_proc_tree()


Tunnel = ResilientTunnel

if __name__ == "__main__":
    t = ResilientTunnel(8765, "1234")
    t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        t.stop()

