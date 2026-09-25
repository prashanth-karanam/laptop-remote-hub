@echo off
chcp 65001 >nul
title Kill Laptop Remote Hub
color 0c
cd /d "%~dp0"

if exist "%~dp0kill_remote.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_remote.ps1"
) else if exist "%~dp0laptop-remote-hub\kill_remote.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0laptop-remote-hub\kill_remote.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*supervisor.py*' -or $_.CommandLine -like '*server.py*') -and $_.ProcessId -ne $PID } | Stop-Process -Force -ErrorAction SilentlyContinue; Stop-Process -Name cloudflared -Force -ErrorAction SilentlyContinue; Write-Host 'Stopped Laptop Remote Hub.' -ForegroundColor Green"
)

echo Press any key to exit...
pause >nul
