@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   VibeRemote Windows 服务端一键启动
echo ============================================

where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo 未检测到 uv，正在自动安装 uv...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

echo 正在同步 Python 依赖（首次运行约需 10-30 秒）...
uv sync
if %errorlevel% neq 0 (
    echo 依赖安装失败，请检查网络连接。
    pause
    exit /b 1
)

echo 正在启动 VibeRemote 服务端...
uv run vibe-server
pause
