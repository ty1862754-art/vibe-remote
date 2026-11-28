from __future__ import annotations

import ctypes
import sys

import numpy as np
from fastapi.testclient import TestClient

from vibe_server.asr_engine import (
    SenseVoiceAsrEngine,
    join_transcript_chunks,
    pcm16_bytes_to_float32,
    split_long_audio,
    trim_silence,
)
from vibe_server.config import AppConfig, AsrConfig, LlmPolishConfig, ServerConfig, apply_hotwords
from vibe_server.main import build_pair_uri, create_app
from vibe_server.protocol import UdpMousePacket, parse_udp_packet
from vibe_server.win_input import INPUT, resolve_vk


def test_parse_udp_packet() -> None:
    assert parse_udp_packet(b"DISCOVER") == "DISCOVER"
    pkt = parse_udp_packet(b"M|123456|12.5|-4.25")
    assert pkt == UdpMousePacket(kind="M", token="123456", dx=12.5, dy=-4.25)

    scroll_pkt = parse_udp_packet(b"W|123456|0|120")
    assert scroll_pkt == UdpMousePacket(kind="W", token="123456", dx=0.0, dy=120.0)

    # Clamping
    clamped = parse_udp_packet(b"M|123456|99999|-99999")
    assert clamped == UdpMousePacket(kind="M", token="123456", dx=2000.0, dy=-2000.0)

    # Invalid payloads
    assert parse_udp_packet(b"X|123456|1|2") is None
    assert parse_udp_packet(b"M|123456|abc|2") is None
    assert parse_udp_packet(b"garbage") is None


def test_apply_hotwords() -> None:
    hotwords = {"巴格": "bug", "韦伯索克特": "WebSocket", "api": "API"}
    src = "帮我修一下这个巴格，把韦伯索克特和api接口改掉"
    assert apply_hotwords(src, hotwords) == "帮我修一下这个bug，把WebSocket和API接口改掉"


def test_pcm16_conversion() -> None:
    samples_i16 = np.array([0, 16384, -16384, 32767], dtype="<i2")
    out = pcm16_bytes_to_float32(samples_i16.tobytes())
    assert out.dtype == np.float32
    assert len(out) == 4
    assert abs(out[0]) < 1e-6
    assert abs(out[1] - 0.5) < 1e-4
    assert abs(out[2] + 0.5) < 1e-4


def test_win32_input_struct_size_and_vk() -> None:
    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(INPUT) == 40
    assert resolve_vk("enter") == 0x0D
    assert resolve_vk("ctrl") == 0x11
    assert resolve_vk("z") == ord("Z")
    assert resolve_vk("nonexistent_key") is None


def test_pair_uri_and_websocket_auth() -> None:
    uri = build_pair_uri("192.168.1.10", 8765, 8766, "654321")
    assert uri == "viberemote://connect?host=192.168.1.10&port=8765&udp=8766&token=654321"

    cfg = AppConfig(server=ServerConfig(token="654321", enable_overlay=False, enable_tray=False))
    app = create_app(cfg, skip_asr_load=True, start_udp=False)

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        pair_resp = client.get("/pair")
        assert pair_resp.status_code == 200
        assert "654321" in pair_resp.text

        # Valid token handshake
        with client.websocket_connect("/ws?token=654321") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["udp_port"] == 8766

            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"


def test_sherpa_onnx_decode_stream_api() -> None:
    import sherpa_onnx

    assert hasattr(sherpa_onnx.OfflineRecognizer, "from_sense_voice")
    assert hasattr(sherpa_onnx.OfflineRecognizer, "create_stream")
    assert hasattr(sherpa_onnx.OfflineRecognizer, "decode_stream")

    class _FakeResult:
        text = "帮我修一下巴格"

    class _FakeStream:
        def __init__(self) -> None:
            self.result = _FakeResult()
            self.received = None

        def accept_waveform(self, sr: int, samples: np.ndarray) -> None:
            self.received = (sr, len(samples))

    class _FakeRecognizer:
        def create_stream(self) -> _FakeStream:
            return _FakeStream()

        def decode_stream(self, stream: _FakeStream) -> None:
            assert stream.received is not None

    engine = SenseVoiceAsrEngine(AsrConfig(), LlmPolishConfig())
    engine._recognizer = _FakeRecognizer()
    engine._ready = True

    # 0.25s of 16kHz PCM16 tone (voiced, so VAD keeps it)
    t = np.arange(4000, dtype=np.float32) / 16000.0
    tone = (0.3 * np.sin(2 * np.pi * 440.0 * t) * 32767.0).astype("<i2")
    res = engine.transcribe_pcm16(tone.tobytes(), sample_rate=16000)
    assert res.raw_text == "帮我修一下巴格"
    assert res.final_text == "帮我修一下bug"
    assert res.chunks == 1


def test_vad_trim_and_long_audio_chunking() -> None:
    sr = 16000
    # 1) Pure low-level noise should be filtered out completely
    quiet = np.full(sr, 0.001, dtype=np.float32)
    assert trim_silence(quiet, sample_rate=sr).size == 0

    # 2) Leading/trailing silence should be trimmed while preserving speech
    t = np.arange(sr, dtype=np.float32) / sr
    speech = 0.25 * np.sin(2 * np.pi * 300.0 * t).astype(np.float32)
    padded = np.concatenate([np.zeros(sr * 2, dtype=np.float32), speech, np.zeros(sr * 2, dtype=np.float32)])
    trimmed = trim_silence(padded, sample_rate=sr)
    assert int(sr * 1.0) <= trimmed.size <= int(sr * 1.6)

    # 3) 36s speech with a quiet pause at 16s should split into 2 chunks near the pause
    seg1 = 0.2 * np.sin(2 * np.pi * 250.0 * (np.arange(sr * 16, dtype=np.float32) / sr)).astype(np.float32)
    pause = np.zeros(int(sr * 0.6), dtype=np.float32)
    seg2 = 0.2 * np.sin(2 * np.pi * 350.0 * (np.arange(sr * 19, dtype=np.float32) / sr)).astype(np.float32)
    long_audio = np.concatenate([seg1, pause, seg2])
    chunks = split_long_audio(long_audio, sample_rate=sr, max_chunk_sec=22.0, min_chunk_sec=12.0)
    assert len(chunks) == 2
    assert 15.5 * sr <= chunks[0].size <= 17.0 * sr

    # 4) Transcript joining handles Chinese and ASCII words cleanly
    assert join_transcript_chunks(["帮我重构", "这个函数"]) == "帮我重构这个函数"
    assert join_transcript_chunks(["fix the", "bug now"]) == "fix the bug now"


def test_semver_comparison() -> None:
    from vibe_server.updater import is_newer_version, parse_semver

    assert parse_semver("v0.3.0") == (0, 3, 0)
    assert is_newer_version("v0.3.1", "0.3.0") is True
    assert is_newer_version("v0.3.0", "0.3.0") is False
    assert is_newer_version("v0.2.9", "0.3.0") is False
    assert is_newer_version("v1.0.0", "0.9.9") is True


def test_websocket_edit_mode_does_not_paste() -> None:
    cfg = AppConfig(server=ServerConfig(token="654321", enable_overlay=False, enable_tray=False))
    app = create_app(cfg, skip_asr_load=True, start_udp=False)

    class _FakeResult:
        text = "帮我打开巴格列表"

    class _FakeStream:
        def __init__(self) -> None:
            self.result = _FakeResult()

        def accept_waveform(self, sr: int, samples: np.ndarray) -> None:
            pass

    class _FakeRecognizer:
        def create_stream(self) -> _FakeStream:
            return _FakeStream()

        def decode_stream(self, stream: _FakeStream) -> None:
            pass

    pasted_calls: list[tuple[str, bool]] = []
    app.state.asr_engine._recognizer = _FakeRecognizer()
    app.state.asr_engine._ready = True
    app.state.controller.paste_text = lambda text, auto_enter=False: (pasted_calls.append((text, auto_enter)) or True)

    t = np.arange(6400, dtype=np.float32) / 16000.0
    tone = (0.3 * np.sin(2 * np.pi * 440.0 * t) * 32767.0).astype("<i2").tobytes()

    with TestClient(app) as client:
        with client.websocket_connect("/ws?token=654321") as ws:
            _ = ws.receive_json()  # hello
            ws.send_json({"type": "audio_start", "sample_rate": 16000, "auto_enter": True})
            _ = ws.receive_json()  # recording
            ws.send_bytes(tone)
            ws.send_json({"type": "audio_end", "mode": "edit"})
            _ = ws.receive_json()  # transcribing
            res = ws.receive_json()
            assert res["type"] == "transcript"
            assert res["mode"] == "edit"
            assert res["final_text"] == "帮我打开bug列表"
            assert res["pasted"] is False
            assert pasted_calls == []


def test_save_and_reload_config(tmp_path) -> None:
    from vibe_server.config import load_config, save_config

    cfg = AppConfig()
    cfg.server.token = "888999"
    cfg.update.github_token = "ghp_test_token"
    cfg.asr.hotwords = {"测试词": "TestWord", "巴格": "bug"}
    cfg.llm_polish.enabled = True
    cfg.llm_polish.model = "deepseek-chat"

    target = tmp_path / "config.toml"
    save_config(cfg, target)
    reloaded = load_config(target)

    assert reloaded.server.token == "888999"
    assert reloaded.update.github_token == "ghp_test_token"
    assert reloaded.asr.hotwords["测试词"] == "TestWord"
    assert reloaded.llm_polish.enabled is True
    assert reloaded.llm_polish.model == "deepseek-chat"


