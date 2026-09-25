@echo off
chcp 65001 >nul
title Start Laptop Remote Hub 24/7 (1-Click Universal)
color 0a
cd /d "%~dp0"

echo ================================================================
echo       LAPTOP REMOTE HUB 24/7 - UNIVERSAL 1-CLICK LAUNCHER        
echo ================================================================
echo.

set "TARGET_PS1="

:: 1. Search in current folder
if exist "%~dp0START_REMOTE_24_7.ps1" set "TARGET_PS1=%~dp0START_REMOTE_24_7.ps1"

:: 2. Search in subfolder
if not defined TARGET_PS1 if exist "%~dp0laptop-remote-hub\START_REMOTE_24_7.ps1" set "TARGET_PS1=%~dp0laptop-remote-hub\START_REMOTE_24_7.ps1"

:: 3. Search in LocalAppData
if not defined TARGET_PS1 if exist "%LOCALAPPDATA%\laptop-remote-hub\START_REMOTE_24_7.ps1" set "TARGET_PS1=%LOCALAPPDATA%\laptop-remote-hub\START_REMOTE_24_7.ps1"

:: 4. Search in UserProfile
if not defined TARGET_PS1 if exist "%USERPROFILE%\laptop-remote-hub\START_REMOTE_24_7.ps1" set "TARGET_PS1=%USERPROFILE%\laptop-remote-hub\START_REMOTE_24_7.ps1"

:: 5. Search in Desktop
if not defined TARGET_PS1 if exist "%USERPROFILE%\Desktop\laptop-remote-hub\START_REMOTE_24_7.ps1" set "TARGET_PS1=%USERPROFILE%\Desktop\laptop-remote-hub\START_REMOTE_24_7.ps1"
if not defined TARGET_PS1 if defined OneDrive if exist "%OneDrive%\Desktop\laptop-remote-hub\START_REMOTE_24_7.ps1" set "TARGET_PS1=%OneDrive%\Desktop\laptop-remote-hub\START_REMOTE_24_7.ps1"

:: 6. Fallback path for development environment
if not defined TARGET_PS1 if exist "C:\Users\Praashu\.gemini\antigravity\scratch\laptop-remote-hub\START_REMOTE_24_7.ps1" set "TARGET_PS1=C:\Users\Praashu\.gemini\antigravity\scratch\laptop-remote-hub\START_REMOTE_24_7.ps1"

if defined TARGET_PS1 (
    echo [*] Launching Remote Hub Engine from: %TARGET_PS1%
    powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET_PS1%"
) else (
    echo [!] Missing project files: START_REMOTE_24_7.ps1 was not found.
    echo.
    echo [*] NOTE FOR FRIENDS / NEW PCS:
    echo     Please extract the entire 'LaptopRemoteHub_Portable_1Click.zip' folder
    echo     and run START_REMOTE_24_7.bat from inside that folder.
    echo     (Do not run the .bat file alone without its companion files).
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo.
echo Press any key to close this status window...
pause >nul
