[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "       STARTING LAPTOP REMOTE HUB 24/7 (1-CLICK ZERO SETUP)     " -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# -------------------------------------------------------------------------
# STEP 1: RESOLVE USER DESKTOP DYNAMICALLY
# -------------------------------------------------------------------------
$desktopDir = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path $desktopDir)) {
    if ($env:OneDrive -and (Test-Path (Join-Path $env:OneDrive "Desktop"))) {
        $desktopDir = Join-Path $env:OneDrive "Desktop"
    } elseif ($env:USERPROFILE -and (Test-Path (Join-Path $env:USERPROFILE "Desktop"))) {
        $desktopDir = Join-Path $env:USERPROFILE "Desktop"
    }
}

# -------------------------------------------------------------------------
# STEP 2: LOCATE HUB DIRECTORY DYNAMICALLY (PORTABLE ACROSS ALL COMPUTERS)
# -------------------------------------------------------------------------
$hubDir = $null
$possibleHubDirs = @(
    $PSScriptRoot,
    (Join-Path $PSScriptRoot "laptop-remote-hub"),
    (Join-Path $env:LOCALAPPDATA "laptop-remote-hub"),
    (Join-Path $env:USERPROFILE "laptop-remote-hub"),
    (Join-Path $desktopDir "laptop-remote-hub"),
    "C:\Users\Praashu\.gemini\antigravity\scratch\laptop-remote-hub"
)

foreach ($dir in $possibleHubDirs) {
    if ($dir -and (Test-Path (Join-Path $dir "server.py")) -and (Test-Path (Join-Path $dir "supervisor.py"))) {
        $hubDir = (Resolve-Path $dir).Path
        break
    }
}

if (-not $hubDir) {
    # Auto-initialize into LocalAppData if running from a loose script
    $targetHub = Join-Path $env:LOCALAPPDATA "laptop-remote-hub"
    if (Test-Path (Join-Path $targetHub "server.py")) {
        $hubDir = $targetHub
    } else {
        Write-Host "[!] Error: Could not locate laptop-remote-hub project files (server.py)." -ForegroundColor Red
        Write-Host "    Please ensure the 'laptop-remote-hub' folder is in the same folder or extracted." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "[*] Hub Location : $hubDir" -ForegroundColor DarkGray
Write-Host "[*] Desktop Path : $desktopDir" -ForegroundColor DarkGray
Write-Host ""

# -------------------------------------------------------------------------
# STEP 3: DISCOVER OR INSTALL PYTHON (ZERO SETUP ON ANY PC)
# -------------------------------------------------------------------------
function Find-PythonExecutable {
    # Check PATH python
    $cmd = Get-Command "python" -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
        try {
            $ver = & $cmd.Source --version 2>&1
            if ($ver -like "*Python 3.*") { return $cmd.Source }
        } catch {}
    }

    # Check 'py' launcher
    $pyCmd = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $pyPath = & $pyCmd.Source -3 -c "import sys; print(sys.executable)" 2>&1
            if ($pyPath -and (Test-Path $pyPath.Trim())) { return $pyPath.Trim() }
        } catch {}
    }

    # Check common install locations
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) { return $cand }
    }

    $found = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }

    return $null
}

$pythonExe = Find-PythonExecutable

if (-not $pythonExe) {
    Write-Host "[*] Python 3 not found. Initiating automated zero-setup install..." -ForegroundColor Yellow
    $wingetCmd = Get-Command "winget" -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Host "    Installing Python 3.12 via winget (silent)..." -ForegroundColor Cyan
        & winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $pythonExe = Find-PythonExecutable
    }

    if (-not $pythonExe) {
        Write-Host "    Downloading official Python 3.12 standalone installer..." -ForegroundColor Cyan
        $pyInstaller = Join-Path $env:TEMP "python-3.12.6-amd64.exe"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe" -OutFile $pyInstaller -UseBasicParsing
            Write-Host "    Running silent installation..." -ForegroundColor Cyan
            Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            $pythonExe = Find-PythonExecutable
        } catch {
            Write-Host "[!] Python download note: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

if (-not $pythonExe) {
    Write-Host "[!] Could not automatically install Python." -ForegroundColor Red
    Write-Host "    Please install Python 3 from python.org or Microsoft Store and run again." -ForegroundColor Yellow
    exit 1
}

Write-Host "[+] Python Runtime: $pythonExe" -ForegroundColor Green

# -------------------------------------------------------------------------
# STEP 4: VERIFY AND AUTO-INSTALL PYTHON DEPENDENCIES
# -------------------------------------------------------------------------
Write-Host "[*] Checking Python dependencies..." -ForegroundColor DarkGray
$depsOk = $false
try {
    $checkProc = & $pythonExe -c "import fastapi, uvicorn, pyautogui, mss, psutil, PIL, qrcode; print('OK')" 2>&1
    if ($checkProc -like "*OK*") {
        $depsOk = $true
    }
} catch {
    $depsOk = $false
}

if (-not $depsOk) {
    Write-Host "[*] Installing missing dependencies (fastapi, uvicorn, pyautogui, mss, psutil, pillow, qrcode)..." -ForegroundColor Yellow
    & $pythonExe -m pip install --quiet --disable-pip-version-check fastapi uvicorn pyautogui mss psutil pillow qrcode
    Write-Host "[+] Dependencies installed successfully!" -ForegroundColor Green
} else {
    Write-Host "[+] All dependencies verified." -ForegroundColor Green
}

# -------------------------------------------------------------------------
# STEP 5: VERIFY CLOUDFLARED BINARY
# -------------------------------------------------------------------------
$cfExe = Join-Path $hubDir "cloudflared.exe"
if (-not (Test-Path $cfExe)) {
    Write-Host "[*] Downloading Cloudflare tunneling agent (cloudflared.exe)..." -ForegroundColor Yellow
    $cfUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $cfUrl -OutFile $cfExe -UseBasicParsing
        Write-Host "[+] Cloudflared downloaded successfully!" -ForegroundColor Green
    } catch {
        Write-Host "[!] Warning: Cloudflared download failed ($($_.Exception.Message)). Will attempt fallback via python." -ForegroundColor Yellow
    }
}

# -------------------------------------------------------------------------
# STEP 6: DYNAMICALLY GENERATE run_background.vbs WITH DETECTED PATHS
# -------------------------------------------------------------------------
$vbsPath = Join-Path $hubDir "run_background.vbs"
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "$hubDir"
WshShell.Run """$pythonExe"" supervisor.py", 0, False
"@
Set-Content -Path $vbsPath -Value $vbsContent -Encoding ASCII

# -------------------------------------------------------------------------
# STEP 7: SYNCHRONIZE DESKTOP LAUNCHERS & KILL SWITCH
# -------------------------------------------------------------------------
$desktopKillBat = Join-Path $desktopDir "KILL_REMOTE.bat"
$desktopKillPs1 = Join-Path $desktopDir "kill_remote.ps1"
$desktopPortal = Join-Path $desktopDir "24_7_REMOTE_PORTAL.html"
$sourceKillBat = Join-Path $hubDir "kill_remote.bat"
$sourceKillPs1 = Join-Path $hubDir "kill_remote.ps1"
$sourcePortal = Join-Path $hubDir "web\portal.html"

if (Test-Path $sourceKillBat) { Copy-Item -Path $sourceKillBat -Destination $desktopKillBat -Force -ErrorAction SilentlyContinue }
if (Test-Path $sourceKillPs1) { Copy-Item -Path $sourceKillPs1 -Destination $desktopKillPs1 -Force -ErrorAction SilentlyContinue }
if (Test-Path $sourcePortal) { Copy-Item -Path $sourcePortal -Destination $desktopPortal -Force -ErrorAction SilentlyContinue }

# -------------------------------------------------------------------------
# STEP 8: LAUNCH OR VERIFY IMMORTAL BACKGROUND DAEMON
# -------------------------------------------------------------------------
$alreadyRunning = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.CommandLine -like '*server.py*' -or $_.CommandLine -like '*supervisor.py*') -and $_.ProcessId -ne $PID
}

$infoFile = Join-Path $hubDir "connection_info.json"

if (-not $alreadyRunning) {
    Write-Host "[*] Launching immortal background daemon (supervisor + server + tunnel)..." -ForegroundColor Yellow
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbsPath`"" -WorkingDirectory $hubDir
    
    # Wait for tunnel negotiation with live progress
    Write-Host "[*] Negotiating secure Cloudflare HTTPS Tunnel & 24/7 Registry Beacon..." -ForegroundColor Cyan
    $maxWait = 15
    $waited = 0
    $hasPublic = $false
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 1
        $waited++
        if (Test-Path $infoFile) {
            try {
                $j = Get-Content $infoFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
                if ($j.public_url -and $j.public_url -like "https://*") {
                    $hasPublic = $true
                    break
                }
            } catch {}
        }
        Write-Host "    Handshaking with Cloudflare edge network ($waited/${maxWait}s)..." -ForegroundColor DarkGray
    }
} else {
    Write-Host "[i] Laptop Remote Hub is already running 24/7 in background." -ForegroundColor Green
}

# -------------------------------------------------------------------------
# STEP 9: DISPLAY LIVE STATUS, PIN, AND 24/7 PORTAL INFO
# -------------------------------------------------------------------------
if (Test-Path $infoFile) {
    try {
        $json = Get-Content $infoFile -Raw | ConvertFrom-Json
        $publicUrl = $json.public_url
        $localUrl = $json.local_url
        $bestUrl = if ($publicUrl) { $publicUrl } else { $localUrl }
        $pin = $json.pin
        $displayPublic = if ($publicUrl) { $publicUrl } else { "(Connecting... check Desktop shortcut in a moment)" }

        Write-Host ""
        Write-Host "================================================================" -ForegroundColor Cyan
        Write-Host "         LAPTOP REMOTE HUB IS ONLINE & RUNNING 24/7             " -ForegroundColor Green
        Write-Host "================================================================" -ForegroundColor Cyan
        Write-Host "  [24/7 WEB PORTAL] : 24_7_REMOTE_PORTAL.html (On Desktop)" -ForegroundColor Yellow
        Write-Host "  [GLOBAL HTTPS]   : $displayPublic" -ForegroundColor Yellow
        Write-Host "  [LOCAL WI-FI]    : $localUrl" -ForegroundColor Cyan
        Write-Host "  [SECURITY PIN]   : $pin" -ForegroundColor White
        Write-Host "----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host "  [Desktop Portal] : Open '24_7_REMOTE_PORTAL.html' on your phone!" -ForegroundColor Green
        Write-Host "                     (Auto-discovers this PC - No copy-pasting needed!)" -ForegroundColor DarkGray
        Write-Host "  [Desktop Stop]   : KILL_REMOTE.bat (Double click anytime to stop)" -ForegroundColor Gray
        Write-Host "  [Stream Mode]    : 60 FPS Ultra-HD WebSocket Screen Mirror Ready" -ForegroundColor Green
        Write-Host "================================================================" -ForegroundColor Cyan
        Write-Host ""

        # Display terminal QR code if URL is available
        if ($bestUrl) {
            Write-Host "Scan this QR code with your phone camera to connect:" -ForegroundColor Yellow
            try {
                & $pythonExe -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); import qrcode; qr = qrcode.QRCode(); qr.add_data('$bestUrl'); qr.print_ascii(invert=True)"
            } catch {}
        }
    } catch {
        Write-Host "[!] Could not parse connection info: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "[!] Initializing tunnel. Check 'OPEN_PHONE_REMOTE' on Desktop in a moment." -ForegroundColor Yellow
}
Write-Host ""
