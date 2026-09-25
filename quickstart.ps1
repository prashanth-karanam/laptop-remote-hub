# ==============================================================================
# Laptop Remote Hub — 1-Line Instant Quickstart for Friend's Laptop
# ==============================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "     CONNECTING LAPTOP TO REMOTE HUB (1-CLICK ZERO SETUP)       " -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

$zipUrl = "https://github.com/prashanth-karanam/laptop-remote-hub/archive/refs/heads/main.zip"
$installDir = Join-Path $env:LOCALAPPDATA "LaptopRemoteHub"
$zipFile = Join-Path $env:TEMP "LaptopRemoteHub.zip"

Write-Host "[1/3] Downloading Remote Hub package..." -ForegroundColor Cyan
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
} catch {
    Write-Host "[!] Download failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "[2/3] Extracting files..." -ForegroundColor Cyan
if (Test-Path $installDir) {
    try { Remove-Item -Path $installDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Expand-Archive -Path $zipFile -DestinationPath $installDir -Force
Remove-Item -Path $zipFile -Force -ErrorAction SilentlyContinue

$hubRoot = Join-Path $installDir "laptop-remote-hub-main"
if (-not (Test-Path $hubRoot)) {
    $hubRoot = $installDir
}

$startScript = Join-Path $hubRoot "START_REMOTE_24_7.ps1"

Write-Host "[3/3] Launching Remote Engine..." -ForegroundColor Green
Write-Host ""

if (Test-Path $startScript) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$startScript"
} else {
    Write-Host "[!] Could not find START_REMOTE_24_7.ps1 in $hubRoot" -ForegroundColor Red
}
