@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "VibeRemoteServer.exe" (
    powershell -Command "Start-Process -FilePath '%~dp0VibeRemoteServer.exe' -Verb RunAs"
) else (
    powershell -Command "Start-Process -FilePath '%~dp0启动服务端.bat' -Verb RunAs"
)
