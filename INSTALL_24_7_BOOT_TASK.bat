@echo off
setlocal
echo =================================================================
echo       INSTALLING LAPTOP REMOTE HUB 24/7 AUTO-START SERVICE       
echo =================================================================
echo.

:: Elevate to Administrator if not already elevated
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] Requesting Administrator privileges to register boot service...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

set "HUB_DIR=%~dp0"
if "%HUB_DIR:~-1%"=="\" set "HUB_DIR=%HUB_DIR:~0,-1%"
set "VBS_PATH=%HUB_DIR%\run_background.vbs"
set "TASK_NAME=LaptopRemoteHub24_7"

echo [*] Target Task: %TASK_NAME%
echo [*] Script Path: %VBS_PATH%
echo.

:: Delete old task if exists
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

:: Create Scheduled Task triggered at System Boot and at Logon
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '\"%VBS_PATH%\"' -WorkingDirectory '%HUB_DIR%';" ^
  "$trigger1 = New-ScheduledTaskTrigger -AtStartup;" ^
  "$trigger2 = New-ScheduledTaskTrigger -AtLogOn;" ^
  "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1);" ^
  "$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest;" ^
  "Register-ScheduledTask -TaskName '%TASK_NAME%' -Action $action -Trigger @($trigger1, $trigger2) -Settings $settings -Principal $principal -Description 'Guarantees Laptop Remote Hub runs 24/7 immediately after restart or boot.' -Force"

if %errorlevel% equ 0 (
    echo.
    echo =================================================================
    echo [OK] 24/7 BOOT SERVICE INSTALLED SUCCESSFULLY!
    echo      The remote hub will start automatically within seconds of
    echo      every reboot, restart, or update.
    echo =================================================================
) else (
    echo [!] Task registration encountered an error.
)

echo.
timeout /t 5
