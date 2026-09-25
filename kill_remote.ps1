$ErrorActionPreference = 'SilentlyContinue'

Write-Host "================================================================" -ForegroundColor Red
Write-Host "         TERMINATING LAPTOP REMOTE HUB & SRM SENTINEL           " -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Red
Write-Host ""

$killedCount = 0

# 1. Kill any python/pythonw running supervisor or server
Get-CimInstance Win32_Process | Where-Object {
    ($_.CommandLine -like '*supervisor.py*' -or $_.CommandLine -like '*server.py*' -or $_.CommandLine -like '*laptop-remote-hub*') -and $_.ProcessId -ne $PID
} | ForEach-Object {
    Write-Host "  [-] Terminating Python process (PID $($_.ProcessId))..." -ForegroundColor Yellow
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    $killedCount++
}

# 2. Kill cloudflared process
Get-Process -Name cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  [-] Terminating Cloudflared process (PID $($_.Id))..." -ForegroundColor Yellow
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    $killedCount++
}

# 3. Clean up any lingering process on port 8765
$netstat = netstat -ano | Select-String ':8765\s+.*LISTENING'
foreach ($line in $netstat) {
    $parts = ($line.ToString().Trim() -split '\s+')
    $portPid = $parts[-1]
    if ($portPid -and $portPid -ne '0') {
        Write-Host "  [-] Freeing Port 8765 (PID $portPid)..." -ForegroundColor Yellow
        Stop-Process -Id $portPid -Force -ErrorAction SilentlyContinue
        $killedCount++
    }
}

# 4. Restore normal Windows power/sleep state
try {
    $code = '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
    $type = Add-Type -MemberDefinition $code -Name 'PowerApi' -Namespace 'Win32' -PassThru
    $type::SetThreadExecutionState(0x80000000)
} catch {}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  [SUCCESS] Laptop Remote Hub & SRM Sentinel are STOPPED." -ForegroundColor Green
Write-Host "  Port 8765 freed. Normal power management restored." -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
