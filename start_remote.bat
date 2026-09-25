@echo off
title Laptop Remote Hub - SRM Sentinel
color 0b
echo ========================================================
echo   LAPTOP REMOTE HUB ^& SRMIST WI-FI SENTINEL
echo ========================================================
echo.
cd /d "%~dp0"

echo [*] Initializing SRM Sentinel ^& Global Access Tunnel...
echo.
python server.py
pause
