@echo off
chcp 65001 >nul
echo 正在请求管理员权限以放行 VibeRemote 局域网端口 (TCP 8765 / UDP 8766)...
powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -Command New-NetFirewallRule -DisplayName \"VibeRemote WS\" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName \"VibeRemote UDP\" -Direction Inbound -Protocol UDP -LocalPort 8766 -Action Allow -ErrorAction SilentlyContinue; Write-Host \"防火墙放行完成！\"; Start-Sleep -Seconds 2'"
