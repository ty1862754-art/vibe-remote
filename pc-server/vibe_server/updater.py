from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import __version__
from .config import BASE_DIR, UpdateConfig

logger = logging.getLogger(__name__)


@dataclass
class ReleaseInfo:
    current_version: str
    latest_version: str
    has_update: bool
    release_url: str
    notes: str
    windows_asset_name: str | None = None
    windows_download_url: str | None = None
    windows_api_url: str | None = None
    android_asset_name: str | None = None
    android_download_url: str | None = None
    android_api_url: str | None = None


def parse_semver(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    nums = [int(x) for x in re.findall(r"\d+", cleaned)]
    return tuple(nums) if nums else (0,)


def is_newer_version(latest: str, current: str) -> bool:
    a = parse_semver(latest)
    b = parse_semver(current)
    max_len = max(len(a), len(b))
    a_pad = a + (0,) * (max_len - len(a))
    b_pad = b + (0,) * (max_len - len(b))
    return a_pad > b_pad


def _github_headers(token: str = "", accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": f"VibeRemote/{__version__}",
    }
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def check_latest_release(
    update_cfg: UpdateConfig,
    current_version: str = __version__,
    timeout: float = 12.0,
) -> ReleaseInfo:
    url = f"https://api.github.com/repos/{update_cfg.github_repo}/releases/latest"
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        resp = client.get(url, headers=_github_headers(update_cfg.github_token))
        if resp.status_code == 404:
            raise RuntimeError("未找到已发布的 Release（如仓库为私有，请在配置中填写 GitHub Token 或将仓库设为公开）")
        resp.raise_for_status()
        data = resp.json()

    tag = str(data.get("tag_name") or "").strip()
    latest_ver = tag.lstrip("vV") or current_version
    release_url = str(data.get("html_url") or f"https://github.com/{update_cfg.github_repo}/releases")
    notes = str(data.get("body") or "").strip()

    win_name = win_dl = win_api = None
    apk_name = apk_dl = apk_api = None
    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        lower = name.lower()
        if lower.endswith(".zip") and "windows" in lower:
            win_name = name
            win_dl = str(asset.get("browser_download_url") or "")
            win_api = str(asset.get("url") or "")
        elif lower.endswith(".apk"):
            apk_name = name
            apk_dl = str(asset.get("browser_download_url") or "")
            apk_api = str(asset.get("url") or "")

    return ReleaseInfo(
        current_version=current_version,
        latest_version=latest_ver,
        has_update=is_newer_version(latest_ver, current_version),
        release_url=release_url,
        notes=notes,
        windows_asset_name=win_name,
        windows_download_url=win_dl,
        windows_api_url=win_api,
        android_asset_name=apk_name,
        android_download_url=apk_dl,
        android_api_url=apk_api,
    )


def download_windows_update(info: ReleaseInfo, update_cfg: UpdateConfig) -> Path:
    if not info.windows_download_url and not info.windows_api_url:
        raise RuntimeError("最新 Release 中未包含 Windows 压缩包")

    updates_dir = BASE_DIR / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    target = updates_dir / (info.windows_asset_name or f"VibeRemote-Windows-v{info.latest_version}.zip")

    use_api = bool(update_cfg.github_token and info.windows_api_url)
    url = info.windows_api_url if use_api else info.windows_download_url
    assert url is not None
    headers = _github_headers(
        update_cfg.github_token,
        accept="application/octet-stream" if use_api else "*/*",
    )

    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=300.0)) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            with target.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 128):
                    f.write(chunk)
    return target
