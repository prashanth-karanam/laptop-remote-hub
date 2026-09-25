@echo off
chcp 65001 >nul
title Package Laptop Remote Hub For Friend (1-Click Zip Creator)
color 0b
cd /d "%~dp0"

echo ================================================================
echo    PACKAGING LAPTOP REMOTE HUB INTO PORTABLE 1-CLICK ZIP
echo ================================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "OUTPUT_ZIP=%USERPROFILE%\Desktop\LaptopRemoteHub_Portable_1Click.zip"
if defined OneDrive if exist "%OneDrive%\Desktop" set "OUTPUT_ZIP=%OneDrive%\Desktop\LaptopRemoteHub_Portable_1Click.zip"

echo [*] Source Directory : %SCRIPT_DIR%
echo [*] Target Zip File  : %OUTPUT_ZIP%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$src = '%SCRIPT_DIR%';" ^
    "$dst = '%OUTPUT_ZIP%';" ^
    "if (Test-Path $dst) { Remove-Item $dst -Force };" ^
    "$tempDir = Join-Path $env:TEMP ('hub_pack_' + (Get-Random));" ^
    "New-Item -ItemType Directory -Path (Join-Path $tempDir 'LaptopRemoteHub') -Force | Out-Null;" ^
    "$targetDir = Join-Path $tempDir 'LaptopRemoteHub';" ^
    "Get-ChildItem -Path $src -Exclude '*.log', '__pycache__', 'hub_*.log', '.git' | ForEach-Object { Copy-Item -Path $_.FullName -Destination $targetDir -Recurse -Force };" ^
    "Compress-Archive -Path (Join-Path $tempDir '*') -DestinationPath $dst -Force;" ^
    "Remove-Item $tempDir -Recurse -Force;" ^
    "Write-Host '[+] Successfully created portable package on Desktop!' -ForegroundColor Green;" ^
    "Write-Host '    File: ' $dst -ForegroundColor Yellow;"

echo.
echo ================================================================
echo   READY TO SHARE! 
echo   Send 'LaptopRemoteHub_Portable_1Click.zip' to your friend.
echo   Your friend only needs to:
echo     1. Extract the zip folder
echo     2. Double-click START_REMOTE_24_7.bat
echo     3. Done! It automatically installs Python, dependencies,
echo        and broadcasts the live 60 FPS mirror link!
echo ================================================================
echo.
pause
