"""
Interactive Desktop Screen Capturer for Windows
-----------------------------------------------
Attaches to WinSta0\\Default interactive session and captures full color desktop frames
with zero Win32 handle leaks and reusable high-speed GDI context.
"""

import sys
import ctypes
from ctypes import windll, wintypes
import io
import time
import threading
from PIL import Image
import mss

user32 = windll.user32

try:
    user32.SetProcessDPIAware()
except Exception:
    pass

_interactive_attached = False
_sct_lock = threading.Lock()
_sct_instance = None


def attach_interactive_desktop():
    """Attaches current process/thread to interactive WinSta0\\Default desktop safely (once)."""
    global _interactive_attached
    if _interactive_attached:
        return
    try:
        hwin = user32.OpenWindowStationA(b"WinSta0", False, 0x0000037F)
        if hwin:
            user32.SetProcessWindowStation(hwin)
        
        hdesk = user32.OpenDesktopA(b"Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
        _interactive_attached = True
    except Exception:
        pass


def get_screen_size():
    try:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def _get_mss():
    global _sct_instance
    if _sct_instance is None:
        _sct_instance = mss.MSS()
    return _sct_instance


def capture_desktop_jpeg(scale: float = 1.0, quality: int = 85) -> bytes:
    """Captures live desktop screen and returns high-definition JPEG bytes with zero handle leakage."""
    attach_interactive_desktop()
    with _sct_lock:
        try:
            sct = _get_mss()
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            sct_img = sct.grab(mon)
            
            # High-speed image creation directly from raw RGB buffer
            with Image.frombytes("RGB", sct_img.size, sct_img.rgb) as img:
                buf = io.BytesIO()
                
                # Determine chroma subsampling: 0 (4:4:4 full color) for ultra high quality, 2 (4:2:0) for fast
                subsampling = 0 if quality >= 80 else 2
                
                if scale < 0.99:
                    nw = max(1, int(img.width * scale))
                    nh = max(1, int(img.height * scale))
                    with img.resize((nw, nh), Image.Resampling.BILINEAR) as resized_img:
                        resized_img.save(buf, format="JPEG", quality=quality, optimize=False, subsampling=subsampling)
                        return buf.getvalue()
                else:
                    # Native resolution 100% scale (no resize overhead)
                    img.save(buf, format="JPEG", quality=quality, optimize=False, subsampling=subsampling)
                    return buf.getvalue()
        except Exception as e:
            # Re-initialize MSS in case display mode changed (e.g. resolution change)
            global _sct_instance
            try:
                if _sct_instance:
                    _sct_instance.close()
            except Exception:
                pass
            _sct_instance = None
            
            # Fallback frame
            with Image.new("RGB", (640, 360), color=(20, 25, 35)) as img:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                return buf.getvalue()


if __name__ == "__main__":
    t0 = time.perf_counter()
    for _ in range(50):
        data = capture_desktop_jpeg(scale=1.0, quality=85)
    dt = time.perf_counter() - t0
    print(f"Captured 50 test frames in {dt:.3f}s ({50/dt:.1f} FPS), frame size: {len(data)} bytes")


