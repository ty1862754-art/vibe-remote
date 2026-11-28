from __future__ import annotations

import logging
import tarfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from .config import AsrConfig, LlmPolishConfig, apply_hotwords, load_config

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    raw_text: str
    final_text: str
    latency_ms: int
    polished: bool = False
    chunks: int = 1


def ensure_sensevoice_model(asr_cfg: AsrConfig) -> tuple[Path, Path]:
    """Ensure SenseVoiceSmall int8 ONNX model and tokens.txt exist locally; download if missing."""
    model_dir = asr_cfg.resolved_model_dir()
    model_file = _find_model_file(model_dir)
    tokens_file = model_dir / "tokens.txt"
    if model_file and tokens_file.exists():
        return model_file, tokens_file

    models_root = model_dir.parent
    models_root.mkdir(parents=True, exist_ok=True)
    archive_path = models_root / "sensevoice_model.tar.bz2"

    logger.info("未检测到本地 SenseVoice 模型，正在自动下载...")
    logger.info("下载地址: %s", asr_cfg.model_url)
    logger.info("提示：如 GitHub 下载较慢，可在 config.toml 修改 model_url 或手动下载解压至 %s", model_dir)

    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=300.0)) as client:
        with client.stream("GET", asr_cfg.model_url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            last_report = 0.0
            with archive_path.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if total and (now - last_report >= 1.5 or downloaded == total):
                        pct = downloaded * 100.0 / total
                        logger.info(
                            "模型下载进度: %.1f%% (%.1f / %.1f MB)",
                            pct,
                            downloaded / (1024 * 1024),
                            total / (1024 * 1024),
                        )
                        last_report = now

    logger.info("下载完成，正在解压模型文件到 %s ...", models_root)
    with tarfile.open(archive_path, "r:bz2") as tar:
        tar.extractall(path=models_root, filter="data")
    try:
        archive_path.unlink(missing_ok=True)
    except OSError:
        pass

    model_file = _find_model_file(model_dir)
    if not model_file or not tokens_file.exists():
        raise FileNotFoundError(
            f"模型解压后未在 {model_dir} 找到 model.int8.onnx / model.onnx 和 tokens.txt"
        )
    logger.info("SenseVoiceSmall 模型准备就绪: %s", model_file)
    return model_file, tokens_file


def _find_model_file(model_dir: Path) -> Path | None:
    for name in ("model.int8.onnx", "model.onnx"):
        candidate = model_dir / name
        if candidate.exists():
            return candidate
    return None


def pcm16_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert signed 16-bit little-endian mono PCM bytes into normalized float32 samples [-1, 1]."""
    if not pcm_bytes:
        return np.zeros(0, dtype=np.float32)
    usable_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
    if usable_len <= 0:
        return np.zeros(0, dtype=np.float32)
    arr = np.frombuffer(pcm_bytes[:usable_len], dtype="<i2").astype(np.float32)
    arr /= 32768.0
    return arr


def _frame_rms(samples: np.ndarray, frame_size: int) -> np.ndarray:
    n_frames = samples.size // frame_size
    if n_frames <= 0:
        return np.zeros(0, dtype=np.float32)
    framed = samples[: n_frames * frame_size].reshape(n_frames, frame_size)
    return np.sqrt(np.mean(framed * framed, axis=1))


def trim_silence(
    samples: np.ndarray,
    sample_rate: int = 16000,
    min_rms: float = 0.008,
    min_voiced_ms: int = 120,
    pad_start_ms: int = 180,
    pad_end_ms: int = 220,
) -> np.ndarray:
    """
    Energy-based VAD that filters pure room noise / accidental brief presses
    and trims leading & trailing silence while preserving natural speech padding.
    """
    frame_ms = 20
    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    rms = _frame_rms(samples, frame_size)
    if rms.size == 0:
        return np.zeros(0, dtype=np.float32)

    peak_rms = float(np.max(rms))
    if peak_rms < min_rms:
        return np.zeros(0, dtype=np.float32)

    noise_floor = float(np.percentile(rms, 15))
    thresh = max(min_rms, min(0.035, noise_floor * 2.5, peak_rms * 0.45))
    voiced = np.flatnonzero(rms >= thresh)
    if voiced.size * frame_ms < min_voiced_ms:
        return np.zeros(0, dtype=np.float32)

    pad_start = int(pad_start_ms / frame_ms)
    pad_end = int(pad_end_ms / frame_ms)
    start_frame = max(0, int(voiced[0]) - pad_start)
    end_frame = min(rms.size, int(voiced[-1]) + 1 + pad_end)
    return samples[start_frame * frame_size : min(samples.size, end_frame * frame_size)]


def split_long_audio(
    samples: np.ndarray,
    sample_rate: int = 16000,
    max_chunk_sec: float = 22.0,
    min_chunk_sec: float = 12.0,
) -> list[np.ndarray]:
    """
    Split audio longer than `max_chunk_sec` at the quietest pause between
    `min_chunk_sec` and `max_chunk_sec` so SenseVoice never truncates >30s speech.
    """
    max_len = int(max_chunk_sec * sample_rate)
    if samples.size <= max_len:
        return [samples] if samples.size > 0 else []

    min_len = int(min_chunk_sec * sample_rate)
    frame_ms = 20
    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    pause_window_frames = 10  # 200ms rolling energy window

    chunks: list[np.ndarray] = []
    start = 0
    total = samples.size

    while start < total:
        remaining = total - start
        if remaining <= max_len:
            tail = samples[start:total]
            if tail.size >= int(0.15 * sample_rate):
                chunks.append(tail)
            break

        search_lo = start + min_len
        search_hi = min(total, start + max_len)
        window = samples[search_lo:search_hi]
        rms = _frame_rms(window, frame_size)

        if rms.size > pause_window_frames:
            kernel = np.ones(pause_window_frames, dtype=np.float32) / pause_window_frames
            smoothed = np.convolve(rms, kernel, mode="valid")
            best_idx = int(np.argmin(smoothed))
            split_pos = search_lo + (best_idx + pause_window_frames // 2) * frame_size
        elif rms.size > 0:
            split_pos = search_lo + int(np.argmin(rms)) * frame_size
        else:
            split_pos = search_hi

        chunks.append(samples[start:split_pos])
        start = split_pos

    return chunks


def join_transcript_chunks(parts: list[str]) -> str:
    """Join chunked transcripts naturally (insert space only between adjacent ASCII words)."""
    cleaned = [p.strip() for p in parts if p and p.strip()]
    if not cleaned:
        return ""
    out = cleaned[0]
    for nxt in cleaned[1:]:
        if out[-1].isascii() and out[-1].isalnum() and nxt[0].isascii() and nxt[0].isalnum():
            out += " " + nxt
        else:
            out += nxt
    return out


class SenseVoiceAsrEngine:
    """Local offline ASR backed by sherpa-onnx + SenseVoiceSmall."""

    def __init__(self, asr_cfg: AsrConfig, llm_cfg: LlmPolishConfig) -> None:
        self.asr_cfg = asr_cfg
        self.llm_cfg = llm_cfg
        self._recognizer = None
        self._ready = False
        self._load_error: str | None = None
        self._decode_lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self, auto_download: bool = True) -> bool:
        try:
            import sherpa_onnx  # type: ignore

            model_dir = self.asr_cfg.resolved_model_dir()
            model_file = _find_model_file(model_dir)
            tokens_file = model_dir / "tokens.txt"

            if not (model_file and tokens_file.exists()):
                if not auto_download:
                    self._load_error = f"模型未下载，请运行 uv run vibe-download-model（目录：{model_dir}）"
                    logger.warning(self._load_error)
                    return False
                model_file, tokens_file = ensure_sensevoice_model(self.asr_cfg)

            t0 = time.perf_counter()
            lang = "" if self.asr_cfg.language.strip().lower() == "auto" else self.asr_cfg.language.strip()
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model_file),
                tokens=str(tokens_file),
                num_threads=self.asr_cfg.num_threads,
                language=lang,
                use_itn=self.asr_cfg.use_itn,
                debug=False,
            )
            self._ready = True
            self._load_error = None
            logger.info("SenseVoiceSmall 加载完成 (耗时 %.2fs)", time.perf_counter() - t0)
            return True
        except Exception as exc:
            self._ready = False
            self._load_error = str(exc)
            logger.exception("加载 SenseVoiceSmall 失败: %s", exc)
            return False

    def transcribe_pcm16(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        use_llm_polish: bool = False,
    ) -> TranscriptResult:
        if not self._ready or self._recognizer is None:
            raise RuntimeError(self._load_error or "ASR 模型尚未就绪")

        t0 = time.perf_counter()
        raw_samples = pcm16_bytes_to_float32(pcm_bytes)
        if raw_samples.size < int(sample_rate * 0.15):
            return TranscriptResult(raw_text="", final_text="", latency_ms=0, polished=False, chunks=0)

        trimmed = trim_silence(raw_samples, sample_rate=sample_rate)
        if trimmed.size < int(sample_rate * 0.12):
            return TranscriptResult(raw_text="", final_text="", latency_ms=0, polished=False, chunks=0)

        chunks = split_long_audio(trimmed, sample_rate=sample_rate)
        chunk_texts: list[str] = []
        with self._decode_lock:
            for chunk in chunks:
                stream = self._recognizer.create_stream()
                stream.accept_waveform(sample_rate, chunk)
                self._recognizer.decode_stream(stream)
                piece = str(stream.result.text).strip()
                if piece:
                    chunk_texts.append(piece)

        raw_text = join_transcript_chunks(chunk_texts)
        final_text = apply_hotwords(raw_text, self.asr_cfg.hotwords)

        polished = False
        if use_llm_polish and final_text and self.llm_cfg.is_available:
            polished_text = self._polish_with_llm(final_text)
            if polished_text:
                final_text = polished_text
                polished = True

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return TranscriptResult(
            raw_text=raw_text,
            final_text=final_text,
            latency_ms=latency_ms,
            polished=polished,
            chunks=len(chunks),
        )

    def transcribe_partial_pcm16(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        max_preview_sec: float = 18.0,
    ) -> str:
        """Fast preview transcription while the user is still holding the button."""
        if not self._ready or self._recognizer is None:
            return ""
        raw_samples = pcm16_bytes_to_float32(pcm_bytes)
        if raw_samples.size < int(sample_rate * 0.35):
            return ""
        max_samples = int(max_preview_sec * sample_rate)
        if raw_samples.size > max_samples:
            raw_samples = raw_samples[-max_samples:]
        trimmed = trim_silence(raw_samples, sample_rate=sample_rate)
        if trimmed.size < int(sample_rate * 0.15):
            return ""
        with self._decode_lock:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(sample_rate, trimmed)
            self._recognizer.decode_stream(stream)
            raw_text = str(stream.result.text).strip()
        return apply_hotwords(raw_text, self.asr_cfg.hotwords)

    def _polish_with_llm(self, text: str) -> str | None:
        url = f"{self.llm_cfg.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.llm_cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.llm_cfg.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": self.llm_cfg.system_prompt},
                {"role": "user", "content": text},
            ],
        }
        try:
            with httpx.Client(timeout=self.llm_cfg.timeout_seconds) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return str(content).strip()
        except Exception as exc:
            logger.warning("LLM 润色失败，已回退原文: %s", exc)
            return None


def cli_download_model() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = load_config()
    ensure_sensevoice_model(cfg.asr)
