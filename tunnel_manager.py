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
        self.candidate_url = None
        self.public_url = None
        self.local_url = f"http://{get_local_ip()}:{self.port}?pin={self.pin}"
        self.process = None
        self.is_running = True
        self.is_edge_registered = False
        self._url_event = threading.Event()
        self._reader_thread = None
        self.tunnel_spawn_time = 0
        self.last_reconnect_attempt = 0
        self.reconnect_counter = 0
        self.needs_respawn = False
        self._spawn_lock = threading.Lock()

    def _pipe_drainer(self, proc):
        """Continuously reads lines from cloudflared stdout/stderr to prevent OS pipe buffer deadlocks and detect edge events."""
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                line_str = line.strip()

                # 1. Parse trycloudflare URL candidate dynamically
                if "trycloudflare.com" in line_str:
                    matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line_str)
                    for m in matches:
                        if "api.trycloudflare.com" not in m:
                            candidate = f"{m}?pin={self.pin}"
                            if candidate != self.candidate_url:
                                self.candidate_url = candidate
                                logger.info(f"Assigned Tunnel URL candidate: {self.candidate_url} (Awaiting edge registration...)")
                            break

                # 2. Detect genuine Edge Registration handshake
                # Cloudflare logs: 'INF Registered tunnel connection connIndex=0 ...'
                if "Registered tunnel connection" in line_str or "Connection registered" in line_str:
                    self.is_edge_registered = True
                    self.reconnect_counter = 0
                    self.last_reconnect_attempt = 0
                    logger.info("Cloudflare Edge Handshake Confirmed (Registered tunnel connection).")

                    if self.candidate_url and self.candidate_url != self.public_url:
                        # Allow 3.5s settling buffer for global Anycast Edge DNS propagation before broadcasting
                        def propagate_and_publish():
                            time.sleep(3.5)
                            if self.is_running and proc.poll() is None and self.candidate_url:
                                self.public_url = self.candidate_url
                                logger.info(f"[PROVISIONAL -> LIVE] Tunnel URL ready & active: {self.public_url}")
                                self._url_event.set()
                                update_shortcuts_and_qr(self.public_url, self.local_url, self.pin)
                        threading.Thread(target=propagate_and_publish, daemon=True).start()
                    else:
                        self._url_event.set()

                # 3. Detect Stuck Reconnect Loops (The 1-Hour Ephemeral Session Drop / Eviction Bug)
                if "Retrying connection" in line_str:
                    now = time.time()
                    if self.last_reconnect_attempt == 0:
                        self.last_reconnect_attempt = now
                    self.reconnect_counter += 1

                    # If retrying connection continuously for > 25 seconds or >= 6 consecutive retries:
                    if (now - self.last_reconnect_attempt > 25) or (self.reconnect_counter >= 6):
                        logger.warning(
                            f"Tunnel connection stuck in retry loop ({self.reconnect_counter} retries, {int(now - self.last_reconnect_attempt)}s). "
                            "Flagging for auto-healing respawn..."
                        )
                        self.needs_respawn = True

                # Log important lines without spamming
                if "ERR" in line_str or "error" in line_str.lower():
                    if "connection closed" in line_str.lower() or "quic" in line_str.lower():
                        logger.warning(f"[Cloudflare Edge] {line_str}")
                    else:
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
        with self._spawn_lock:
            self._kill_proc_tree()
            self._url_event.clear()
            self.candidate_url = None
            self.public_url = None
            self.is_edge_registered = False
            self.reconnect_counter = 0
            self.last_reconnect_attempt = 0
            self.needs_respawn = False
            self.tunnel_spawn_time = time.time()

            binary = ensure_cloudflared()
            if not binary:
                logger.error("Cloudflared binary not available. Operating in LAN-only mode.")
                update_shortcuts_and_qr(None, self.local_url, self.pin)
                return None

            cfg = load_custom_config()
            token = cfg.get("cloudflare_token") or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN")
            custom_domain = cfg.get("custom_domain")

            if token:
                logger.info("Spawning persistent Cloudflare Named Tunnel via Token (HTTP2/TCP443)...")
                cmd = [
                    binary, "tunnel", "run",
                    "--token", token,
                    "--no-autoupdate",
                    "--protocol", "http2",
                    "--edge-ip-version", "4",
                    "--heartbeat-count", "10",
                    "--heartbeat-interval", "5s"
                ]
                if custom_domain:
                    self.public_url = f"https://{custom_domain}?pin={self.pin}"
            else:
                logger.info("Spawning Cloudflare Global Quick Tunnel (HTTP2/TCP443 IPv4) with auto keep-alives...")
                cmd = [
                    binary, "tunnel",
                    "--url", f"http://127.0.0.1:{self.port}",
                    "--no-autoupdate",
                    "--protocol", "http2",
                    "--edge-ip-version", "4",
                    "--heartbeat-count", "10",
                    "--heartbeat-interval", "5s",
                    "--retries", "30"
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
                # Wait up to 35 seconds for tunnel edge registration
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
        """Active health watchdog: verifies process health and auto-revives only if genuinely crashed or stale."""
        while self.is_running:
            time.sleep(10)
            if not self.is_running:
                break

            now = time.time()

            # 1. Auto-Healing Reconnect Trap: Check if flagged for respawn due to stuck retry loop
            if self.needs_respawn:
                logger.warning("Reviving stale/dropped tunnel (Auto-Healing Reconnect Trap)...")
                self.needs_respawn = False
                self._spawn_tunnel()
                continue

            # 2. Check if cloudflared process terminated
            if self.process is None or self.process.poll() is not None:
                logger.warning("Cloudflare tunnel process terminated. Reviving tunnel daemon...")
                self._spawn_tunnel()
                continue

            # 3. Ephemeral Quick Tunnel Maximum Session Age Protection (~75 min safety refresh)
            # Free trycloudflare tunnels get forcefully recycled by Cloudflare edge after 60-90 minutes.
            # Proactively recycling before the hard edge eviction prevents sudden dead link freezes.
            cfg = load_custom_config()
            has_token = bool(cfg.get("cloudflare_token") or os.environ.get("CLOUDFLARE_TUNNEL_TOKEN"))
            if not has_token and self.tunnel_spawn_time > 0:
                uptime_mins = (now - self.tunnel_spawn_time) / 60.0
                if uptime_mins >= 75:
                    logger.info(f"Quick Tunnel session age is {int(uptime_mins)}m (approaching Cloudflare 90m limit). Performing seamless session refresh...")
                    self._spawn_tunnel()
                    continue

            # 4. Verify local server is listening
            try:
                local_probe = f"http://127.0.0.1:{self.port}/api/health"
                req_local = urllib.request.Request(local_probe, headers={"User-Agent": "TunnelWatchdog/2.0"})
                with urllib.request.urlopen(req_local, timeout=4) as resp:
                    pass
            except Exception:
                pass

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

