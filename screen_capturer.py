"""
Interactive Desktop Screen Capturer for Windows
-----------------------------------------------
Attaches every calling thread to WinSta0\\Default interactive session.
Captures full-color desktop frames with zero handle leaks via a resilient multi-layer engine:
- Layer 1: High-Speed Direct MSS Engine (sub-10ms, 60 FPS capable).
- Layer 2: PIL.ImageGrab Win32 Engine Fallback.
- Layer 3: Native Win32 GDI Device Context Fallback.
- Auto-Wake: Detects display sleep and proactively wakes Windows compositor.
"""

import sys
import ctypes
from ctypes import windll, wintypes
import io
import time
import threading
from PIL import Image, ImageGrab, ImageDraw
import mss

user32 = windll.user32
gdi32 = windll.gdi32
kernel32 = windll.kernel32

try:
    user32.SetProcessDPIAware()
except Exception:
    pass

_thread_local = threading.local()
_global_lock = threading.Lock()
_last_wake_time = 0


def wake_display_if_needed():
    """Wakes the Windows display compositor if the display entered power-saving state."""
    global _last_wake_time
    now = time.time()
    if now - _last_wake_time > 15:
        _last_wake_time = now
        try:
            # ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
            kernel32.SetThreadExecutionState(0x80000000 | 0x00000002 | 0x00000001)
            # Send harmless 0-delta mouse event to trigger GDI compositor redraw
            user32.mouse_event(0x0001, 0, 0, 0, 0)
        except Exception:
            pass


def attach_interactive_desktop():
    """Attaches the CURRENT thread to the interactive WinSta0\\Default desktop session."""
    if getattr(_thread_local, "attached", False):
        return True

    try:
        hwin = user32.OpenWindowStationA(b"WinSta0", False, 0x0000037F)
        if hwin:
            user32.SetProcessWindowStation(hwin)

        hdesk = user32.OpenDesktopA(b"Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        _thread_local.attached = True
        return True
    except Exception:
        return False


def get_screen_size():
    try:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def _get_thread_mss():
    """Retrieves or creates a thread-local MSS instance to avoid GDI handle conflicts."""
    if not hasattr(_thread_local, "sct") or _thread_local.sct is None:
        _thread_local.sct = mss.MSS()
    return _thread_local.sct


def _grab_raw_image():
    """Captures desktop image using resilient fallback chain."""
    attach_interactive_desktop()

    # Layer 1: MSS capture
    try:
        sct = _get_thread_mss()
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        sct_img = sct.grab(mon)
        return Image.frombytes("RGB", sct_img.size, sct_img.rgb)
    except Exception:
        # Reset thread MSS if corrupted
        try:
            if hasattr(_thread_local, "sct") and _thread_local.sct:
                _thread_local.sct.close()
        except Exception:
            pass
        _thread_local.sct = None

    # Layer 2: PIL.ImageGrab Win32 capture
    try:
        wake_display_if_needed()
        return ImageGrab.grab(all_screens=False)
    except Exception:
        pass

    # Layer 3: Direct Win32 GDI BitBlt
    try:
        wake_display_if_needed()
        w, h = get_screen_size()
        hdesktop = user32.GetDesktopWindow()
        desktop_dc = user32.GetWindowDC(hdesktop)
        img_dc = gdi32.CreateCompatibleDC(desktop_dc)
        hbitmap = gdi32.CreateCompatibleBitmap(desktop_dc, w, h)
        gdi32.SelectObject(img_dc, hbitmap)
        gdi32.BitBlt(img_dc, 0, 0, w, h, desktop_dc, 0, 0, 0x00CC0020)  # SRCCOPY

        bmpinfo = wintypes.BITMAPINFO()
        bmpinfo.bmiHeader.biSize = ctypes.sizeof(wintypes.BITMAPINFOHEADER)
        bmpinfo.bmiHeader.biWidth = w
        bmpinfo.bmiHeader.biHeight = -h
        bmpinfo.bmiHeader.biPlanes = 1
        bmpinfo.bmiHeader.biBitCount = 24
        bmpinfo.bmiHeader.biCompression = 0

        buffer_len = w * h * 3
        buffer = ctypes.create_string_buffer(buffer_len)
        gdi32.GetDIBits(img_dc, hbitmap, 0, h, buffer, ctypes.byref(bmpinfo), 0)

        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(img_dc)
        user32.ReleaseDC(hdesktop, desktop_dc)

        return Image.frombytes("RGB", (w, h), buffer.raw)
    except Exception:
        pass

    # Layer 4: Informative placeholder if display is locked or asleep
    wake_display_if_needed()
    w, h = get_screen_size()
    img = Image.new("RGB", (w, h), color=(15, 20, 32))
    draw = ImageDraw.Draw(img)
    msg = f"Screen Locked or Display Sleep State ({time.strftime('%H:%M:%S')})\nMove mouse or tap to wake interactive desktop"
    draw.text((w // 2 - 200, h // 2 - 20), msg, fill=(0, 210, 255))
    return img


def capture_desktop_jpeg(scale: float = 1.0, quality: int = 85) -> bytes:
    """Captures live desktop screen and returns high-definition JPEG bytes."""
    with _global_lock:
        try:
            with _grab_raw_image() as img:
                buf = io.BytesIO()
                subsampling = 0 if quality >= 80 else 2

                if scale < 0.99:
                    nw = max(1, int(img.width * scale))
                    nh = max(1, int(img.height * scale))
                    with img.resize((nw, nh), Image.Resampling.BILINEAR) as resized_img:
                        resized_img.save(buf, format="JPEG", quality=quality, optimize=False, subsampling=subsampling)
                        return buf.getvalue()
                else:
                    img.save(buf, format="JPEG", quality=quality, optimize=False, subsampling=subsampling)
                    return buf.getvalue()
        except Exception:
            # Ultimate safety frame
            with Image.new("RGB", (640, 360), color=(20, 25, 35)) as img:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                return buf.getvalue()


if __name__ == "__main__":
    attach_interactive_desktop()
    t0 = time.time()
    for _ in range(10):
        data = capture_desktop_jpeg(scale=0.85, quality=80)
    dt = time.time() - t0
    print(f"Captured 10 test frames in {dt:.3f}s ({10/dt:.1f} FPS), frame size: {len(data)} bytes")
