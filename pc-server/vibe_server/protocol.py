from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UdpMousePacket:
    kind: str  # "M" (move) or "W" (wheel)
    token: str
    dx: float
    dy: float


def parse_udp_packet(data: bytes) -> UdpMousePacket | str | None:
    """
    Parse compact UDP payloads:
      - "DISCOVER" -> returns "DISCOVER"
      - "M|<token>|<dx>|<dy>" -> UdpMousePacket("M", ...)
      - "W|<token>|<dx>|<dy>" -> UdpMousePacket("W", ...)
    """
    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None

    if text == "DISCOVER":
        return "DISCOVER"

    parts = text.split("|")
    if len(parts) != 4:
        return None
    kind, token, raw_dx, raw_dy = parts
    if kind not in ("M", "W"):
        return None
    try:
        dx = float(raw_dx)
        dy = float(raw_dy)
    except ValueError:
        return None

    # Sanity clamp to avoid rogue values jumping across screens
    dx = max(-2000.0, min(2000.0, dx))
    dy = max(-2000.0, min(2000.0, dy))
    return UdpMousePacket(kind=kind, token=token, dx=dx, dy=dy)
