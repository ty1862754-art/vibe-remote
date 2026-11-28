from __future__ import annotations

import queue
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UiEvent:
    kind: str  # "log" | "clients" | "asr" | "overlay" | "show_window" | "quit"
    payload: object = None


class ServerStateHub:
    """Thread-safe bridge between FastAPI/ASR background threads and the Desktop GUI main thread."""

    def __init__(self) -> None:
        self.events: queue.Queue[UiEvent] = queue.Queue()
        self.connected_clients: int = 0
        self.asr_state: str = "loading"
        self.asr_detail: str = "正在加载 SenseVoiceSmall 模型..."

    def push_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.put(UiEvent("log", f"[{ts}] {message}"))

    def set_clients(self, count: int, last_ip: str = "") -> None:
        self.connected_clients = max(0, count)
        self.events.put(UiEvent("clients", (self.connected_clients, last_ip)))

    def set_asr(self, state: str, detail: str) -> None:
        self.asr_state = state
        self.asr_detail = detail
        self.events.put(UiEvent("asr", (state, detail)))

    def push_overlay(self, state: str, message: str = "", auto_hide_ms: int = 0) -> None:
        self.events.put(UiEvent("overlay", (state, message, auto_hide_ms)))

    def request_show_window(self) -> None:
        self.events.put(UiEvent("show_window", None))

    def request_quit(self) -> None:
        self.events.put(UiEvent("quit", None))
