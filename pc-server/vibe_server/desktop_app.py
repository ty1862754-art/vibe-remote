from __future__ import annotations

import ctypes
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Callable

import customtkinter as ctk
import qrcode
from PIL import Image

from . import __version__
from .config import AppConfig, save_config
from .overlay import (
    GWL_EXSTYLE,
    STATE_STYLE,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
)
from .state_hub import ServerStateHub
from .tray import (
    is_autostart_enabled,
    relaunch_as_admin,
    set_autostart_enabled,
)
from .updater import check_latest_release, download_windows_update
from .win_input import is_admin

logger = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

BG_DARK = "#0B0F17"
CARD_DARK = "#141925"
ELEVATED_DARK = "#1E2536"
BORDER_DARK = "#2B3449"
ACCENT_BLUE = "#3B82F6"
ACCENT_GREEN = "#10B981"
ACCENT_AMBER = "#F59E0B"
ACCENT_RED = "#EF4444"
TEXT_PRIMARY = "#F3F4F6"
TEXT_MUTED = "#9CA3AF"


def _resource_path(filename: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "vibe_server" / filename
    return Path(__file__).resolve().parent / filename


def _apply_dark_titlebar(window: tk.Misc) -> None:
    if not IS_WINDOWS:
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        val = ctypes.c_int(1)
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win11 / Win10 20H1+)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def _make_qr_pil_image(uri: str, size: int = 204) -> Image.Image:
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF").convert("RGB")
    return img.resize((size, size), Image.Resampling.NEAREST)


def _allow_windows_firewall_uac() -> None:
    if not IS_WINDOWS:
        return
    cmd = (
        'New-NetFirewallRule -DisplayName "VibeRemote WS" -Direction Inbound -Protocol TCP '
        '-LocalPort 8765 -Action Allow -ErrorAction SilentlyContinue; '
        'New-NetFirewallRule -DisplayName "VibeRemote UDP" -Direction Inbound -Protocol UDP '
        '-LocalPort 8766 -Action Allow -ErrorAction SilentlyContinue'
    )
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe", f"-NoProfile -WindowStyle Hidden -Command {subprocess.list2cmdline([cmd])}", None, 0
        )
    except Exception as exc:
        logger.warning("请求放行防火墙失败: %s", exc)


class IntegratedOverlay:
    """Non-focus-stealing bottom floating pill hosted on the main GUI Tk interpreter."""

    def __init__(self, master: tk.Misc, enabled: bool = True) -> None:
        self.enabled = enabled and IS_WINDOWS
        self._master = master
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._hide_job: str | None = None
        if IS_WINDOWS:
            self._init_window()

    def _init_window(self) -> None:
        win = tk.Toplevel(self._master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.94)
        win.configure(bg="#18181B")
        label = tk.Label(
            win,
            text="",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg="#FFFFFF",
            bg="#18181B",
            padx=20,
            pady=9,
        )
        label.pack()
        win.withdraw()
        try:
            win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_style = style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        except Exception:
            pass
        self._win = win
        self._label = label

    def show(self, state: str, message: str = "", auto_hide_ms: int = 0) -> None:
        if not self.enabled or self._win is None or self._label is None:
            return
        if self._hide_job is not None:
            try:
                self._win.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if state == "hide":
            self._win.withdraw()
            return

        bg, fg, default_prefix = STATE_STYLE.get(state, ("#27272A", "#FFFFFF", ""))
        display = message if message else default_prefix
        if len(display) > 42:
            display = display[:41] + "…"
        self._win.configure(bg=bg)
        self._label.configure(text=display, bg=bg, fg=fg)
        self._win.update_idletasks()
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        w = self._win.winfo_reqwidth()
        h = self._win.winfo_reqheight()
        self._win.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, sh - h - 76)}")
        self._win.deiconify()
        if auto_hide_ms > 0:
            self._hide_job = self._win.after(auto_hide_ms, self._win.withdraw)


class VibeRemoteDesktopApp:
    """Modern dark Windows desktop application for VibeRemote (no black console window)."""

    def __init__(
        self,
        *,
        cfg: AppConfig,
        hub: ServerStateHub,
        lan_ip: str,
        pair_uri: str,
        pair_url: str,
        debug_url: str,
        on_quit: Callable[[], None],
        start_minimized: bool = False,
    ) -> None:
        self.cfg = cfg
        self.hub = hub
        self.lan_ip = lan_ip
        self.pair_uri = pair_uri
        self.pair_url = pair_url
        self.debug_url = debug_url
        self.on_quit = on_quit
        self.start_minimized = start_minimized

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(f"VibeRemote v{__version__}")
        self.root.geometry("880x600")
        self.root.minsize(820, 560)
        self.root.configure(fg_color=BG_DARK)

        ico_path = _resource_path("viberemote.ico")
        if ico_path.exists():
            try:
                self.root.iconbitmap(str(ico_path))
            except Exception:
                pass
        _apply_dark_titlebar(self.root)

        self.overlay = IntegratedOverlay(self.root, enabled=cfg.server.enable_overlay)
        self._qr_ctk_image = ctk.CTkImage(light_image=_make_qr_pil_image(pair_uri, 200), size=(200, 200))

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        self._center_window()

        if self.start_minimized:
            self.root.withdraw()

        self.root.after(60, self._poll_events)

    def _center_window(self) -> None:
        self.root.update_idletasks()
        w, h = 880, 600
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    def _build_ui(self) -> None:
        # 1. Header Bar
        header = ctk.CTkFrame(self.root, fg_color=CARD_DARK, corner_radius=14, border_width=1, border_color=BORDER_DARK)
        header.pack(fill="x", padx=16, pady=(14, 10))

        left_h = ctk.CTkFrame(header, fg_color="transparent")
        left_h.pack(side="left", padx=16, pady=12)

        ctk.CTkLabel(
            left_h,
            text="VibeRemote",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkLabel(
            left_h,
            text=f" v{__version__} ",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg_color=ELEVATED_DARK,
            text_color=ACCENT_BLUE,
            corner_radius=8,
            padx=6,
            pady=2,
        ).pack(side="left", padx=(10, 8))

        if is_admin():
            ctk.CTkLabel(
                left_h,
                text=" 🛡 管理员权限 ",
                font=("Microsoft YaHei UI", 11, "bold"),
                fg_color="#064E3B",
                text_color="#34D399",
                corner_radius=8,
                padx=6,
                pady=2,
            ).pack(side="left")
        else:
            ctk.CTkButton(
                left_h,
                text="⚠ 普通权限 · 点此提权",
                font=("Microsoft YaHei UI", 11, "bold"),
                fg_color="#78350F",
                hover_color="#92400E",
                text_color="#FCD34D",
                height=26,
                corner_radius=8,
                command=self._handle_elevate,
            ).pack(side="left")

        right_h = ctk.CTkFrame(header, fg_color="transparent")
        right_h.pack(side="right", padx=14, pady=10)

        self.conn_badge = ctk.CTkLabel(
            right_h,
            text=" ● 等待手机连接 ",
            font=("Microsoft YaHei UI", 12, "bold"),
            fg_color=ELEVATED_DARK,
            text_color=TEXT_MUTED,
            corner_radius=10,
            padx=10,
            pady=4,
        )
        self.conn_badge.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            right_h,
            text="最小化到托盘",
            font=("Microsoft YaHei UI", 12),
            fg_color=ELEVATED_DARK,
            hover_color=BORDER_DARK,
            height=30,
            width=102,
            corner_radius=9,
            command=self.root.withdraw,
        ).pack(side="left")

        # 2. Main Tabview
        tabs = ctk.CTkTabview(
            self.root,
            fg_color=BG_DARK,
            segmented_button_fg_color=CARD_DARK,
            segmented_button_selected_color=ACCENT_BLUE,
            segmented_button_unselected_color=CARD_DARK,
            corner_radius=12,
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        tab_home = tabs.add("控制台与扫码配对")
        tab_settings = tabs.add("热词 · AI润色 · 更新配置")

        self._build_home_tab(tab_home)
        self._build_settings_tab(tab_settings)

    def _build_home_tab(self, parent: ctk.CTkFrame) -> None:
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="both", expand=True, pady=(6, 0))
        container.grid_columnconfigure(0, weight=0)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(0, weight=1)

        # Left column: QR pairing card
        qr_card = ctk.CTkFrame(
            container,
            width=280,
            fg_color=CARD_DARK,
            corner_radius=16,
            border_width=1,
            border_color=BORDER_DARK,
        )
        qr_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        qr_card.grid_propagate(False)

        ctk.CTkLabel(
            qr_card,
            text="手机扫码一键连接",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        ctk.CTkLabel(
            qr_card,
            text="确保手机与电脑在同一 Wi-Fi 下",
            font=("Microsoft YaHei UI", 11),
            text_color=TEXT_MUTED,
        ).pack(pady=(0, 10))

        qr_wrap = ctk.CTkFrame(qr_card, fg_color="#FFFFFF", corner_radius=14)
        qr_wrap.pack(pady=4)
        ctk.CTkLabel(qr_wrap, text="", image=self._qr_ctk_image).pack(padx=10, pady=10)

        info_box = ctk.CTkFrame(qr_card, fg_color=ELEVATED_DARK, corner_radius=12)
        info_box.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            info_box,
            text=f"IP: {self.lan_ip}   端口: {self.cfg.server.ws_port}/{self.cfg.server.udp_port}",
            font=("Consolas", 11),
            text_color=TEXT_MUTED,
        ).pack(pady=(8, 2))

        token_row = ctk.CTkFrame(info_box, fg_color="transparent")
        token_row.pack(pady=(0, 8))
        ctk.CTkLabel(
            token_row,
            text=f"配对码: {self.cfg.server.token}",
            font=("Consolas", 15, "bold"),
            text_color=ACCENT_BLUE,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            token_row,
            text="复制",
            width=46,
            height=24,
            font=("Microsoft YaHei UI", 11),
            fg_color=BORDER_DARK,
            hover_color=ACCENT_BLUE,
            command=self._copy_token,
        ).pack(side="left")

        self.asr_badge = ctk.CTkLabel(
            qr_card,
            text="⏳ 正在加载 SenseVoice 模型...",
            font=("Microsoft YaHei UI", 11, "bold"),
            text_color=ACCENT_AMBER,
            wraplength=246,
        )
        self.asr_badge.pack(pady=(6, 12), padx=12)

        # Right column: Controls + Live speech feed
        right_col = ctk.CTkFrame(container, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_rowconfigure(1, weight=1)
        right_col.grid_columnconfigure(0, weight=1)

        ctrl_card = ctk.CTkFrame(
            right_col,
            fg_color=CARD_DARK,
            corner_radius=16,
            border_width=1,
            border_color=BORDER_DARK,
        )
        ctrl_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        switches_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        switches_row.pack(fill="x", padx=16, pady=(14, 10))

        self.autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        ctk.CTkSwitch(
            switches_row,
            text="开机自动启动（静默进托盘）",
            variable=self.autostart_var,
            font=("Microsoft YaHei UI", 12),
            command=self._toggle_autostart,
        ).pack(side="left", padx=(0, 22))

        self.overlay_var = tk.BooleanVar(value=self.cfg.server.enable_overlay)
        ctk.CTkSwitch(
            switches_row,
            text="桌面录音状态浮窗",
            variable=self.overlay_var,
            font=("Microsoft YaHei UI", 12),
            command=self._toggle_overlay,
        ).pack(side="left")

        btn_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(
            btn_row,
            text="🔥 放行防火墙",
            font=("Microsoft YaHei UI", 12),
            fg_color=ELEVATED_DARK,
            hover_color=BORDER_DARK,
            height=34,
            command=self._handle_firewall,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.update_btn = ctk.CTkButton(
            btn_row,
            text="🔄 检查更新",
            font=("Microsoft YaHei UI", 12),
            fg_color=ELEVATED_DARK,
            hover_color=BORDER_DARK,
            height=34,
            command=self._handle_check_update,
        )
        self.update_btn.pack(side="left", expand=True, fill="x", padx=6)

        ctk.CTkButton(
            btn_row,
            text="🌐 网页调试端",
            font=("Microsoft YaHei UI", 12),
            fg_color=ELEVATED_DARK,
            hover_color=BORDER_DARK,
            height=34,
            command=lambda: webbrowser.open(self.debug_url),
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        # Live Activity Card
        log_card = ctk.CTkFrame(
            right_col,
            fg_color=CARD_DARK,
            corner_radius=16,
            border_width=1,
            border_color=BORDER_DARK,
        )
        log_card.grid(row=1, column=0, sticky="nsew")

        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            log_hdr,
            text="实时语音识别与连接动态",
            font=("Microsoft YaHei UI", 14, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkButton(
            log_hdr,
            text="清空",
            width=54,
            height=24,
            font=("Microsoft YaHei UI", 11),
            fg_color=ELEVATED_DARK,
            hover_color=BORDER_DARK,
            command=self._clear_log,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_card,
            fg_color=BG_DARK,
            text_color=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 12),
            corner_radius=10,
            border_width=1,
            border_color=BORDER_DARK,
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log_box.configure(state="disabled")
        self._append_log(f"VibeRemote v{__version__} 桌面应用已启动，等待手机扫码连接。")

    def _build_settings_tab(self, parent: ctk.CTkFrame) -> None:
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, pady=(4, 0))

        # Update Token Section
        upd_card = ctk.CTkFrame(scroll, fg_color=CARD_DARK, corner_radius=14, border_width=1, border_color=BORDER_DARK)
        upd_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            upd_card,
            text="GitHub 更新配置（私有仓库检查更新用）",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.gh_token_entry = ctk.CTkEntry(
            upd_card,
            placeholder_text="只读 Fine-grained Token (github_pat_...)",
            show="*",
            fg_color=BG_DARK,
            border_color=BORDER_DARK,
        )
        self.gh_token_entry.pack(fill="x", padx=16, pady=(0, 12))
        if self.cfg.update.github_token:
            self.gh_token_entry.insert(0, self.cfg.update.github_token)

        # AI Polish Section
        llm_card = ctk.CTkFrame(scroll, fg_color=CARD_DARK, corner_radius=14, border_width=1, border_color=BORDER_DARK)
        llm_card.pack(fill="x", pady=(0, 10))
        llm_hdr = ctk.CTkFrame(llm_card, fg_color="transparent")
        llm_hdr.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(llm_hdr, text="AI 语音润色（可选，OpenAI 兼容接口）", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        self.llm_enabled_var = tk.BooleanVar(value=self.cfg.llm_polish.enabled)
        ctk.CTkSwitch(llm_hdr, text="启用", variable=self.llm_enabled_var, font=("Microsoft YaHei UI", 12)).pack(side="right")

        llm_grid = ctk.CTkFrame(llm_card, fg_color="transparent")
        llm_grid.pack(fill="x", padx=16, pady=(0, 12))
        llm_grid.grid_columnconfigure(0, weight=2)
        llm_grid.grid_columnconfigure(1, weight=1)

        self.llm_url_entry = ctk.CTkEntry(llm_grid, placeholder_text="Base URL (如 https://api.deepseek.com/v1)", fg_color=BG_DARK, border_color=BORDER_DARK)
        self.llm_url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.llm_url_entry.insert(0, self.cfg.llm_polish.base_url)

        self.llm_model_entry = ctk.CTkEntry(llm_grid, placeholder_text="模型名 (如 deepseek-chat)", fg_color=BG_DARK, border_color=BORDER_DARK)
        self.llm_model_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.llm_model_entry.insert(0, self.cfg.llm_polish.model)

        self.llm_key_entry = ctk.CTkEntry(llm_grid, placeholder_text="API Key", show="*", fg_color=BG_DARK, border_color=BORDER_DARK)
        self.llm_key_entry.grid(row=1, column=0, columnspan=2, sticky="ew")
        if self.cfg.llm_polish.api_key:
            self.llm_key_entry.insert(0, self.cfg.llm_polish.api_key)

        # Hotwords Section
        hw_card = ctk.CTkFrame(scroll, fg_color=CARD_DARK, corner_radius=14, border_width=1, border_color=BORDER_DARK)
        hw_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            hw_card,
            text="编程热词纠错表（每行一条，格式：易错词=正确词）",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.hotwords_box = ctk.CTkTextbox(hw_card, height=110, fg_color=BG_DARK, border_width=1, border_color=BORDER_DARK, font=("Consolas", 12))
        self.hotwords_box.pack(fill="x", padx=16, pady=(0, 12))
        hw_text = "\n".join(f"{k}={v}" for k, v in self.cfg.asr.hotwords.items())
        self.hotwords_box.insert("1.0", hw_text)

        # Save Button Row
        save_row = ctk.CTkFrame(scroll, fg_color="transparent")
        save_row.pack(fill="x", pady=(2, 8))
        ctk.CTkButton(
            save_row,
            text="保存配置（立即生效）",
            font=("Microsoft YaHei UI", 13, "bold"),
            fg_color=ACCENT_BLUE,
            hover_color="#2563EB",
            height=38,
            command=self._handle_save_settings,
        ).pack(side="left")
        self.save_status_lbl = ctk.CTkLabel(save_row, text="", font=("Microsoft YaHei UI", 12), text_color=ACCENT_GREEN)
        self.save_status_lbl.pack(side="left", padx=14)

    def _append_log(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _copy_token(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.cfg.server.token)
        self._append_log(f"已复制 6 位配对码: {self.cfg.server.token}")

    def _toggle_autostart(self) -> None:
        want = bool(self.autostart_var.get())
        ok = set_autostart_enabled(want)
        self._append_log("已开启开机自启" if (want and ok) else "已关闭开机自启")

    def _toggle_overlay(self) -> None:
        want = bool(self.overlay_var.get())
        self.cfg.server.enable_overlay = want
        self.overlay.enabled = want and IS_WINDOWS
        if not want:
            self.overlay.show("hide")
        try:
            save_config(self.cfg)
        except Exception:
            pass

    def _handle_elevate(self) -> None:
        if relaunch_as_admin():
            self.on_quit()
            self.root.quit()

    def _handle_firewall(self) -> None:
        _allow_windows_firewall_uac()
        self._append_log("已请求系统放行局域网防火墙端口 (TCP 8765 / UDP 8766)。")

    def _handle_check_update(self) -> None:
        self.update_btn.configure(state="disabled", text="检查中...")

        def worker() -> None:
            try:
                info = check_latest_release(self.cfg.update, __version__)
                if not info.has_update:
                    self.hub.push_log(f"✅ 当前已是最新版本 v{info.current_version}")
                    self.hub.push_overlay("done", f"✅ 已是最新版本 v{info.current_version}", 2400)
                else:
                    self.hub.push_log(f"🆕 发现新版本 v{info.latest_version}，正在下载安装包...")
                    self.hub.push_overlay("polishing", f"⬇ 正在下载 v{info.latest_version}...")
                    try:
                        zip_path = download_windows_update(info, self.cfg.update)
                        self.hub.push_log(f"✅ 已下载新版到 {zip_path}")
                        self.hub.push_overlay("done", f"✅ 新版已下载到 updates/", 3000)
                        if IS_WINDOWS:
                            os.startfile(str(zip_path.parent))  # type: ignore[attr-defined]
                    except Exception:
                        webbrowser.open(info.release_url)
                        self.hub.push_log(f"已打开 Release 下载页: {info.release_url}")
            except Exception as exc:
                self.hub.push_log(f"⚠ 检查更新失败: {exc}")
                self.hub.push_overlay("error", f"⚠ 检查更新失败", 2600)
            finally:
                self.root.after(0, lambda: self.update_btn.configure(state="normal", text="🔄 检查更新"))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_save_settings(self) -> None:
        self.cfg.update.github_token = self.gh_token_entry.get().strip()
        self.cfg.llm_polish.enabled = bool(self.llm_enabled_var.get())
        self.cfg.llm_polish.base_url = self.llm_url_entry.get().strip().rstrip("/") or "https://api.openai.com/v1"
        self.cfg.llm_polish.model = self.llm_model_entry.get().strip() or "gpt-4o-mini"
        self.cfg.llm_polish.api_key = self.llm_key_entry.get().strip()

        new_hotwords: dict[str, str] = {}
        raw_hw = self.hotwords_box.get("1.0", "end").splitlines()
        for line in raw_hw:
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    new_hotwords[k.strip()] = v.strip()
        self.cfg.asr.hotwords = new_hotwords

        try:
            saved_path = save_config(self.cfg)
            self.save_status_lbl.configure(text=f"✅ 已保存到 {saved_path.name} 并立即生效", text_color=ACCENT_GREEN)
            self._append_log("已保存最新热词与 AI/更新配置。")
        except Exception as exc:
            self.save_status_lbl.configure(text=f"⚠ 保存失败: {exc}", text_color=ACCENT_RED)

    def _on_close_button(self) -> None:
        if self.cfg.server.enable_tray:
            self.root.withdraw()
        else:
            self.on_quit()
            self.root.quit()

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.hub.events.get_nowait()
                if ev.kind == "log":
                    self._append_log(str(ev.payload))
                elif ev.kind == "clients":
                    count, last_ip = ev.payload  # type: ignore[misc]
                    if count > 0:
                        txt = f" ● 手机已连接 ({last_ip}) " if last_ip else f" ● 已连接 {count} 台设备 "
                        self.conn_badge.configure(text=txt, fg_color="#064E3B", text_color="#34D399")
                    else:
                        self.conn_badge.configure(text=" ● 等待手机连接 ", fg_color=ELEVATED_DARK, text_color=TEXT_MUTED)
                elif ev.kind == "asr":
                    state, detail = ev.payload  # type: ignore[misc]
                    color = ACCENT_GREEN if state == "ready" else (ACCENT_RED if state == "error" else ACCENT_AMBER)
                    self.asr_badge.configure(text=str(detail), text_color=color)
                elif ev.kind == "overlay":
                    st, msg, hide_ms = ev.payload  # type: ignore[misc]
                    self.overlay.show(st, msg, hide_ms)
                elif ev.kind == "show_window":
                    self.root.deiconify()
                    self.root.lift()
                    self.root.focus_force()
                elif ev.kind == "quit":
                    self.root.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(60, self._poll_events)

    def run(self) -> None:
        self.root.mainloop()
