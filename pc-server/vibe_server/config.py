from __future__ import annotations

import os
import re
import secrets
import socket
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.toml"
TOKEN_FILE_PATH = BASE_DIR / ".vibe_token"

DEFAULT_HOTWORDS: dict[str, str] = {
    "巴格": "bug",
    "吉特": "Git",
    "派森": "Python",
    "瑞艾克特": "React",
    "韦伯索克特": "WebSocket",
    "艾皮艾": "API",
}


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    ws_port: int = 8765
    udp_port: int = 8766
    token: str = ""
    enable_overlay: bool = True
    enable_tray: bool = True
    start_minimized: bool = False


@dataclass
class InputConfig:
    mouse_sensitivity: float = 1.0
    scroll_sensitivity: float = 1.0
    clipboard_restore_delay_ms: int = 120


@dataclass
class AsrConfig:
    model_dir: str = "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    model_url: str = (
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
    )
    num_threads: int = 4
    language: str = "auto"
    use_itn: bool = True
    hotwords: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTWORDS))

    def resolved_model_dir(self) -> Path:
        p = Path(self.model_dir)
        return p if p.is_absolute() else (BASE_DIR / p)


@dataclass
class LlmPolishConfig:
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 10.0
    system_prompt: str = (
        "你是一个程序员的语音转写整理助手。请把用户的中英混合口述内容整理成简洁、准确、"
        "无口癖（去掉呃/那个/就是说等）的文本，自动修正明显读错的编程术语拼写。"
        "保留原意，不要回答问题，只输出整理后的最终文本。"
    )

    @property
    def is_available(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model)


@dataclass
class UpdateConfig:
    github_repo: str = "ty1862754-art/vibe-remote"
    github_token: str = ""


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    input: InputConfig = field(default_factory=InputConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    llm_polish: LlmPolishConfig = field(default_factory=LlmPolishConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)


def _load_or_create_persistent_token() -> str:
    """Persist a random 6-digit pairing token locally so the phone can reconnect across restarts."""
    if TOKEN_FILE_PATH.exists():
        saved = TOKEN_FILE_PATH.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    token = f"{secrets.randbelow(1_000_000):06d}"
    try:
        TOKEN_FILE_PATH.write_text(token, encoding="utf-8")
    except OSError:
        pass
    return token


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    raw: dict = {}
    if path.exists():
        with path.open("rb") as f:
            raw = tomllib.load(f)

    srv_raw = raw.get("server", {})
    inp_raw = raw.get("input", {})
    asr_raw = raw.get("asr", {})
    llm_raw = raw.get("llm_polish", {})
    upd_raw = raw.get("update", {})

    hotwords = dict(DEFAULT_HOTWORDS)
    if isinstance(asr_raw.get("hotwords"), dict):
        hotwords.update({str(k): str(v) for k, v in asr_raw["hotwords"].items()})

    token = os.environ.get("VIBE_TOKEN") or str(srv_raw.get("token") or "").strip()
    if not token:
        token = _load_or_create_persistent_token()

    cfg = AppConfig(
        server=ServerConfig(
            host=str(srv_raw.get("host", "0.0.0.0")),
            ws_port=int(srv_raw.get("ws_port", 8765)),
            udp_port=int(srv_raw.get("udp_port", 8766)),
            token=token,
            enable_overlay=bool(srv_raw.get("enable_overlay", True)),
            enable_tray=bool(srv_raw.get("enable_tray", True)),
            start_minimized=bool(srv_raw.get("start_minimized", False)),
        ),
        input=InputConfig(
            mouse_sensitivity=float(inp_raw.get("mouse_sensitivity", 1.0)),
            scroll_sensitivity=float(inp_raw.get("scroll_sensitivity", 1.0)),
            clipboard_restore_delay_ms=int(inp_raw.get("clipboard_restore_delay_ms", 120)),
        ),
        asr=AsrConfig(
            model_dir=str(
                asr_raw.get(
                    "model_dir",
                    "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
                )
            ),
            model_url=os.environ.get("VIBE_MODEL_URL")
            or str(
                asr_raw.get(
                    "model_url",
                    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2",
                )
            ),
            num_threads=int(asr_raw.get("num_threads", 4)),
            language=str(asr_raw.get("language", "auto")),
            use_itn=bool(asr_raw.get("use_itn", True)),
            hotwords=hotwords,
        ),
        llm_polish=LlmPolishConfig(
            enabled=bool(llm_raw.get("enabled", False)),
            base_url=str(llm_raw.get("base_url", "https://api.openai.com/v1")).rstrip("/"),
            api_key=os.environ.get("VIBE_LLM_API_KEY") or str(llm_raw.get("api_key", "")),
            model=str(llm_raw.get("model", "gpt-4o-mini")),
            timeout_seconds=float(llm_raw.get("timeout_seconds", 10.0)),
            system_prompt=str(
                llm_raw.get(
                    "system_prompt",
                    LlmPolishConfig.system_prompt,
                )
            ),
        ),
        update=UpdateConfig(
            github_repo=str(upd_raw.get("github_repo", "ty1862754-art/vibe-remote")).strip(),
            github_token=os.environ.get("VIBE_GITHUB_TOKEN") or str(upd_raw.get("github_token", "")).strip(),
        ),
    )
    return cfg


def _toml_str(val: str) -> str:
    escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def save_config(cfg: AppConfig, config_path: Path | None = None) -> Path:
    """Persist AppConfig cleanly to config.toml."""
    path = config_path or DEFAULT_CONFIG_PATH
    lines = [
        "# VibeRemote 自动保存的配置文件",
        "",
        "[server]",
        f"host = {_toml_str(cfg.server.host)}",
        f"ws_port = {cfg.server.ws_port}",
        f"udp_port = {cfg.server.udp_port}",
        f"token = {_toml_str(cfg.server.token)}",
        f"enable_overlay = {'true' if cfg.server.enable_overlay else 'false'}",
        f"enable_tray = {'true' if cfg.server.enable_tray else 'false'}",
        f"start_minimized = {'true' if cfg.server.start_minimized else 'false'}",
        "",
        "[update]",
        f"github_repo = {_toml_str(cfg.update.github_repo)}",
        f"github_token = {_toml_str(cfg.update.github_token)}",
        "",
        "[input]",
        f"mouse_sensitivity = {cfg.input.mouse_sensitivity}",
        f"scroll_sensitivity = {cfg.input.scroll_sensitivity}",
        f"clipboard_restore_delay_ms = {cfg.input.clipboard_restore_delay_ms}",
        "",
        "[asr]",
        f"model_dir = {_toml_str(cfg.asr.model_dir)}",
        f"model_url = {_toml_str(cfg.asr.model_url)}",
        f"num_threads = {cfg.asr.num_threads}",
        f"language = {_toml_str(cfg.asr.language)}",
        f"use_itn = {'true' if cfg.asr.use_itn else 'false'}",
        "",
        "[asr.hotwords]",
    ]
    for k, v in cfg.asr.hotwords.items():
        if k.strip():
            lines.append(f"{_toml_str(k.strip())} = {_toml_str(v.strip())}")
    lines.extend([
        "",
        "[llm_polish]",
        f"enabled = {'true' if cfg.llm_polish.enabled else 'false'}",
        f"base_url = {_toml_str(cfg.llm_polish.base_url)}",
        f"api_key = {_toml_str(cfg.llm_polish.api_key)}",
        f"model = {_toml_str(cfg.llm_polish.model)}",
        f"timeout_seconds = {cfg.llm_polish.timeout_seconds}",
        f"system_prompt = {_toml_str(cfg.llm_polish.system_prompt)}",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def apply_hotwords(text: str, hotwords: dict[str, str]) -> str:
    """Apply case-insensitive hotword replacements sorted by descending key length."""
    if not text or not hotwords:
        return text
    result = text
    for src in sorted(hotwords.keys(), key=len, reverse=True):
        if not src:
            continue
        pattern = re.compile(re.escape(src), re.IGNORECASE)
        result = pattern.sub(hotwords[src], result)
    return result


def get_lan_ip() -> str:
    """Detect the primary LAN IPv4 address reachable on local Wi-Fi."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"
