from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from .win_input import is_admin

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "VibeRemoteServer"

SW_HIDE = 0
SW_SHOW = 5


def get_console_hwnd() -> int:
    if not IS_WINDOWS:
        return 0
    try:
        return int(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return 0


def set_console_visible(visible: bool) -> bool:
    hwnd = get_console_hwnd()
    if not hwnd:
        return False
    try:
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW if visible else SW_HIDE)
        return True
    except Exception as exc:
        logger.debug("ShowWindow failed: %s", exc)
        return False


def is_console_visible() -> bool:
    hwnd = get_console_hwnd()
    if not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def build_autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --minimized'
    pc_server_dir = Path(__file__).resolve().parent.parent
    run_script = pc_server_dir / "run_server.py"
    return f'"{Path(sys.executable).resolve()}" "{run_script}" --minimized'


def relaunch_as_admin() -> bool:
    """Relaunch the current server elevated via Windows UAC so it can control Admin windows."""
    if not IS_WINDOWS:
        return False
    try:
        if getattr(sys, "frozen", False):
            exe = str(Path(sys.executable).resolve())
            params = " ".join(subprocess.list2cmdline([a]) for a in sys.argv[1:])
        else:
            exe = str(Path(sys.executable).resolve())
            run_script = str(Path(__file__).resolve().parent.parent / "run_server.py")
            params = subprocess.list2cmdline([run_script, *sys.argv[1:]])
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, SW_SHOW)
        return int(ret) > 32
    except Exception as exc:
        logger.warning("请求管理员权限重启失败: %s", exc)
        return False


def is_autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return bool(str(val).strip())
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("Read autostart registry failed: %s", exc)
        return False


def set_autostart_enabled(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, build_autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as exc:
        logger.warning("更新开机自启失败: %s", exc)
        return False


def _create_tray_image():
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Dark rounded badge
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=14, fill=(17, 24, 39, 255), outline=(59, 130, 246, 255), width=3)
    # Microphone capsule
    draw.rounded_rectangle((24, 14, 40, 38), radius=8, fill=(59, 130, 246, 255))
    # Microphone stand arc + base
    draw.arc((18, 22, 46, 46), start=0, end=180, fill=(147, 197, 253, 255), width=3)
    draw.line((32, 46, 32, 53), fill=(147, 197, 253, 255), width=3)
    draw.line((23, 53, 41, 53), fill=(147, 197, 253, 255), width=3)
    return img


class SystemTrayController:
    """Windows system tray icon for silent background operation, QR page access, and autostart."""

    def __init__(
        self,
        *,
        enabled: bool,
        pair_url: str,
        display_endpoint: str,
        on_quit: Callable[[], None],
    ) -> None:
        self.enabled = enabled and IS_WINDOWS
        self.pair_url = pair_url
        self.display_endpoint = display_endpoint
        self.on_quit = on_quit
        self._icon = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run, name="vibe-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def _run(self) -> None:
        try:
            import pystray
        except Exception as exc:
            logger.warning("无法启动系统托盘图标 (pystray 不可用): %s", exc)
            return

        def open_pair(icon, item) -> None:
            webbrowser.open(self.pair_url)

        def toggle_console(icon, item) -> None:
            set_console_visible(not is_console_visible())

        def toggle_autostart(icon, item) -> None:
            set_autostart_enabled(not is_autostart_enabled())

        def handle_elevate(icon, item) -> None:
            if relaunch_as_admin():
                icon.stop()
                self.on_quit()

        def handle_quit(icon, item) -> None:
            icon.stop()
            self.on_quit()

        admin_tag = " [管理员]" if is_admin() else " [普通权限]"
        menu_items = [
            pystray.MenuItem(f"VibeRemote ({self.display_endpoint}){admin_tag}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开扫码配对页", open_pair, default=True),
            pystray.MenuItem(
                "显示控制台窗口",
                toggle_console,
                checked=lambda item: is_console_visible(),
            ),
            pystray.MenuItem(
                "开机自动启动",
                toggle_autostart,
                checked=lambda item: is_autostart_enabled(),
            ),
        ]
        if not is_admin():
            menu_items.append(pystray.MenuItem("以管理员权限重启（控制所有窗口）", handle_elevate))
        menu_items.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 VibeRemote", handle_quit),
        ])
        menu = pystray.Menu(*menu_items)

        try:
            self._icon = pystray.Icon("VibeRemote", _create_tray_image(), "VibeRemote 控制器", menu)
            self._icon.run()
        except Exception as exc:
            logger.warning("系统托盘运行异常: %s", exc)
            if self._icon is None:
                os._exit(0)
