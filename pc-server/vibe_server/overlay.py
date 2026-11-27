from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

STATE_STYLE = {
    "recording": ("#E53935", "#FFFFFF", "🎙 正在录音..."),
    "transcribing": ("#F59E0B", "#111827", "⏳ 语音识别中..."),
    "polishing": ("#6366F1", "#FFFFFF", "✨ AI 润色中..."),
    "done": ("#10B981", "#FFFFFF", "✅ 已输入"),
    "error": ("#DC2626", "#FFFFFF", "⚠ 识别失败"),
}


class StatusOverlay:
    """Non-focus-stealing bottom-center floating status pill on Windows."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and IS_WINDOWS
        self._queue: queue.Queue[tuple[str, str, int] | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run_tk, name="vibe-overlay", daemon=True)
        self._thread.start()

    def show(self, state: str, message: str = "", auto_hide_ms: int = 0) -> None:
        if not self.enabled:
            return
        self._queue.put((state, message, auto_hide_ms))

    def hide(self) -> None:
        if not self.enabled:
            return
        self._queue.put(("hide", "", 0))

    def stop(self) -> None:
        if not self.enabled:
            return
        self._queue.put(None)

    def _run_tk(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            logger.warning("无法启动桌面状态浮窗 (tkinter 不可用): %s", exc)
            return

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)
        root.configure(bg="#18181B")

        label = tk.Label(
            root,
            text="",
            font=("Microsoft YaHei UI", 11, "bold"),
            fg="#FFFFFF",
            bg="#18181B",
            padx=18,
            pady=8,
        )
        label.pack()
        root.withdraw()

        # Apply WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT so IDE never loses focus
        try:
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_style = style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        except Exception as exc:
            logger.debug("SetWindowLongW overlay hint failed: %s", exc)

        hide_after_id: list[str | None] = [None]

        def cancel_hide() -> None:
            if hide_after_id[0] is not None:
                try:
                    root.after_cancel(hide_after_id[0])
                except Exception:
                    pass
                hide_after_id[0] = None

        def position_bottom_center() -> None:
            root.update_idletasks()
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            w = root.winfo_reqwidth()
            h = root.winfo_reqheight()
            x = max(0, (sw - w) // 2)
            y = max(0, sh - h - 76)
            root.geometry(f"+{x}+{y}")

        def poll_queue() -> None:
            try:
                while True:
                    item = self._queue.get_nowait()
                    if item is None:
                        root.destroy()
                        return
                    state, message, auto_hide_ms = item
                    cancel_hide()
                    if state == "hide":
                        root.withdraw()
                        continue
                    bg, fg, default_prefix = STATE_STYLE.get(state, ("#27272A", "#FFFFFF", ""))
                    display = message if message else default_prefix
                    if len(display) > 42:
                        display = display[:41] + "…"
                    root.configure(bg=bg)
                    label.configure(text=display, bg=bg, fg=fg)
                    position_bottom_center()
                    root.deiconify()
                    if auto_hide_ms > 0:
                        hide_after_id[0] = root.after(auto_hide_ms, root.withdraw)
            except queue.Empty:
                pass
            root.after(40, poll_queue)

        root.after(40, poll_queue)
        try:
            root.mainloop()
        except Exception:
            pass
