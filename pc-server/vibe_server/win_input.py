from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# SendInput constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("_union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_union", _INPUT_UNION),
    ]


VK_MAP: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "super": 0x5B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24,  # PgUp, PgDn, End, Home
    0x25, 0x26, 0x27, 0x28,  # Arrow keys
    0x2E, 0x5B,              # Delete, Left Win
}


def resolve_vk(name: str) -> int | None:
    key = name.strip().lower()
    if key in VK_MAP:
        return VK_MAP[key]
    if len(key) == 1:
        ch = key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
    return None


class WindowsInputController:
    """Low-latency Windows SendInput + safe Unicode clipboard injector."""

    def __init__(
        self,
        mouse_sensitivity: float = 1.0,
        scroll_sensitivity: float = 1.0,
        clipboard_restore_delay_ms: int = 120,
    ) -> None:
        self.mouse_sensitivity = mouse_sensitivity
        self.scroll_sensitivity = scroll_sensitivity
        self.clipboard_restore_delay_ms = clipboard_restore_delay_ms
        self._rem_x = 0.0
        self._rem_y = 0.0
        self._scroll_rem_x = 0.0
        self._scroll_rem_y = 0.0
        self._lock = threading.Lock()

        if IS_WINDOWS:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._setup_win32_prototypes()
        else:
            self._user32 = None
            self._kernel32 = None

    def _setup_win32_prototypes(self) -> None:
        u = self._user32
        k = self._kernel32
        assert u is not None and k is not None

        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        u.SendInput.restype = wintypes.UINT

        u.OpenClipboard.argtypes = [wintypes.HWND]
        u.OpenClipboard.restype = wintypes.BOOL
        u.CloseClipboard.argtypes = []
        u.CloseClipboard.restype = wintypes.BOOL
        u.EmptyClipboard.argtypes = []
        u.EmptyClipboard.restype = wintypes.BOOL
        u.GetClipboardData.argtypes = [wintypes.UINT]
        u.GetClipboardData.restype = wintypes.HANDLE
        u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u.SetClipboardData.restype = wintypes.HANDLE
        u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        u.IsClipboardFormatAvailable.restype = wintypes.BOOL

        k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k.GlobalAlloc.restype = wintypes.HGLOBAL
        k.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k.GlobalLock.restype = wintypes.LPVOID
        k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        k.GlobalUnlock.restype = wintypes.BOOL
        k.GlobalFree.argtypes = [wintypes.HGLOBAL]
        k.GlobalFree.restype = wintypes.HGLOBAL

    def _send_inputs(self, items: list[INPUT]) -> int:
        if not IS_WINDOWS or self._user32 is None or not items:
            return 0
        arr = (INPUT * len(items))(*items)
        sent = self._user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))
        if sent != len(items):
            logger.warning("SendInput sent %d/%d events (err=%d)", sent, len(items), ctypes.get_last_error())
        return int(sent)

    def move_mouse(self, dx: float, dy: float) -> None:
        with self._lock:
            self._rem_x += dx * self.mouse_sensitivity
            self._rem_y += dy * self.mouse_sensitivity
            ix = int(self._rem_x)
            iy = int(self._rem_y)
            self._rem_x -= ix
            self._rem_y -= iy

        if ix == 0 and iy == 0:
            return
        evt = INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(dx=ix, dy=iy, mouseData=0, dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=0),
        )
        self._send_inputs([evt])

    def scroll(self, dx: float, dy: float) -> None:
        """Scroll wheel: dy > 0 scrolls up, dy < 0 scrolls down (Windows convention)."""
        with self._lock:
            self._scroll_rem_x += dx * self.scroll_sensitivity
            self._scroll_rem_y += dy * self.scroll_sensitivity
            ix = int(self._scroll_rem_x)
            iy = int(self._scroll_rem_y)
            self._scroll_rem_x -= ix
            self._scroll_rem_y -= iy

        events: list[INPUT] = []
        if iy != 0:
            events.append(
                INPUT(
                    type=INPUT_MOUSE,
                    mi=MOUSEINPUT(
                        dx=0,
                        dy=0,
                        mouseData=ctypes.c_uint32(iy).value,
                        dwFlags=MOUSEEVENTF_WHEEL,
                        time=0,
                        dwExtraInfo=0,
                    ),
                )
            )
        if ix != 0:
            events.append(
                INPUT(
                    type=INPUT_MOUSE,
                    mi=MOUSEINPUT(
                        dx=0,
                        dy=0,
                        mouseData=ctypes.c_uint32(ix).value,
                        dwFlags=MOUSEEVENTF_HWHEEL,
                        time=0,
                        dwExtraInfo=0,
                    ),
                )
            )
        if events:
            self._send_inputs(events)

    def mouse_click(self, button: str = "left", action: str = "click") -> None:
        flag_map = {
            "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }
        flags = flag_map.get(button.lower())
        if not flags:
            logger.warning("Unknown mouse button: %s", button)
            return
        down_flag, up_flag = flags

        def _evt(f: int) -> INPUT:
            return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, f, 0, 0))

        act = action.lower()
        if act == "click":
            self._send_inputs([_evt(down_flag), _evt(up_flag)])
        elif act == "double":
            self._send_inputs([_evt(down_flag), _evt(up_flag)])
            time.sleep(0.035)
            self._send_inputs([_evt(down_flag), _evt(up_flag)])
        elif act == "down":
            self._send_inputs([_evt(down_flag)])
        elif act == "up":
            self._send_inputs([_evt(up_flag)])

    def press_keys(self, keys: list[str]) -> None:
        vks = [vk for k in keys if (vk := resolve_vk(k)) is not None]
        if not vks:
            logger.warning("No valid virtual keys resolved from: %s", keys)
            return

        events: list[INPUT] = []
        for vk in vks:
            flags = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0)))
        for vk in reversed(vks):
            flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0)
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0)))

        self._send_inputs(events)

    def _open_clipboard_retry(self, retries: int = 8, delay: float = 0.015) -> bool:
        if not IS_WINDOWS or self._user32 is None:
            return False
        for _ in range(retries):
            if self._user32.OpenClipboard(None):
                return True
            time.sleep(delay)
        return False

    def _get_clipboard_text(self) -> str | None:
        if not self._open_clipboard_retry():
            return None
        assert self._user32 is not None and self._kernel32 is not None
        try:
            if not self._user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            handle = self._user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = self._kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                self._kernel32.GlobalUnlock(handle)
        finally:
            self._user32.CloseClipboard()

    def _set_clipboard_text(self, text: str) -> bool:
        if not self._open_clipboard_retry():
            return False
        assert self._user32 is not None and self._kernel32 is not None
        try:
            self._user32.EmptyClipboard()
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            h_mem = self._kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not h_mem:
                return False
            ptr = self._kernel32.GlobalLock(h_mem)
            if not ptr:
                self._kernel32.GlobalFree(h_mem)
                return False
            try:
                ctypes.memmove(ptr, encoded, len(encoded))
            finally:
                self._kernel32.GlobalUnlock(h_mem)
            if not self._user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                self._kernel32.GlobalFree(h_mem)
                return False
            return True
        finally:
            self._user32.CloseClipboard()

    def paste_text(self, text: str, auto_enter: bool = False) -> bool:
        """Paste Unicode text cleanly into the currently focused window via clipboard + Ctrl+V."""
        if not text:
            return False
        if not IS_WINDOWS:
            logger.info("[Non-Windows Mock] paste_text: %r (auto_enter=%s)", text, auto_enter)
            return True

        with self._lock:
            previous_text = self._get_clipboard_text()
            if not self._set_clipboard_text(text):
                logger.error("Failed to write text to Windows clipboard")
                return False

            time.sleep(0.025)
            self.press_keys(["ctrl", "v"])

            if auto_enter:
                time.sleep(0.04)
                self.press_keys(["enter"])

            if previous_text is not None:
                restore_delay = max(0.06, self.clipboard_restore_delay_ms / 1000.0)
                time.sleep(restore_delay)
                self._set_clipboard_text(previous_text)
        return True
