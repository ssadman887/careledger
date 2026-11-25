<#
.SYNOPSIS
  Start (or stop) the whole CareLedger stack natively: Garnet (Redis), API, worker, web.

.DESCRIPTION
  The native replacement for `docker compose up`. PostgreSQL runs as a Windows service.
  Each app process opens in its own minimized window with its logs; close a window to stop it,
  or run `.\scripts\dev.ps1 -Stop` to stop them all.

.PARAMETER Stop
  Stop the API, worker, web and Garnet processes started by this script.

.PARAMETER Production
  Serve a production build of the web app (`next build` + `next start`) instead of `next dev`.
#>
param([switch]$Stop, [switch]$Production)

. (Join-Path $PSScriptRoot "common.ps1")

function Stop-Port([int]$Port, [string]$Name) {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        try { Stop-Process -Id $id -Force -Confirm:$false -ErrorAction Stop; Write-Ok "Stopped $Name (pid $id)" } catch {}
    }
}

function Stop-Tree([int]$ProcessId) {
    # Kill a process and all of its descendants (venv python.exe is a launcher with a child).
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Tree $_.ProcessId }
    try { Stop-Process -Id $ProcessId -Force -Confirm:$false -ErrorAction Stop } catch {}
}

if ($Stop) {
    Write-Step "Stopping CareLedger"
    $windows = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object { $_.CommandLine -like "*WindowTitle = 'CareLedger *" }
    foreach ($w in $windows) { Stop-Tree $w.ProcessId }
    Write-Ok "Closed $(@($windows).Count) app window(s) (API, worker, web)"
    # Anything still holding the ports (e.g. started by hand).
    Stop-Port 3000 "web"
    Stop-Port 8000 "api"
    Stop-Port 6379 "Garnet"
    Write-Ok "PostgreSQL keeps running as a Windows service."
    return
}

if (-not (Test-Path $VenvPython)) { throw "backend\.venv missing. Run .\scripts\setup.ps1 first." }

Write-Step "Infrastructure"
Assert-Postgres
Start-Garnet

Write-Step "Database migrations"
Push-Location $Backend
try { Invoke-Checked "alembic upgrade" { & $VenvPython -m alembic upgrade head } } finally { Pop-Location }

$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $Logs | Out-Null

function Start-AppWindow([string]$Title, [string]$WorkDir, [string]$Command) {
    # Each app gets its own minimized window; output is also written (UTF-8) to logs\<title>.log.
    $log = Join-Path $Logs "$($Title.ToLower()).log"
    $script = "`$host.UI.RawUI.WindowTitle = 'CareLedger $Title'; Set-Location '$WorkDir'; " +
        "`$env:Path = '$env:Path'; `$env:PYTHONUNBUFFERED = '1'; " +
        "Set-Content -Path '$log' -Value '' -Encoding UTF8; " +
        "& { $Command } 2>&1 | ForEach-Object { `$line = `"`$_`"; `$line; Add-Content -Path '$log' -Value `$line -Encoding UTF8 }"
    Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-Command", $script -WindowStyle Minimized | Out-Null
}

Write-Step "Applications"
if (Test-PortListening 8000) { Write-Ok "API already running on 8000" }
else { Start-AppWindow "API" $Backend "& '$VenvPython' -m uvicorn app.main:app --reload --port 8000" }

$workerRunning = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*celery*app.jobs.worker*" }
if ($workerRunning) { Write-Ok "Worker already running" }
else {
    # --pool=solo: Celery's prefork pool is not supported on Windows.
    Start-AppWindow "worker" $Backend "& '$VenvPython' -m celery -A app.jobs.worker worker --loglevel=info --pool=solo --without-mingle --without-gossip"
    $deadline = (Get-Date).AddSeconds(60)
    $workerLog = Join-Path $Logs "worker.log"
    while ((Get-Date) -lt $deadline -and -not ((Test-Path $workerLog) -and (Select-String -Path $workerLog -Pattern " ready\." -Quiet))) {
        Start-Sleep -Milliseconds 500
    }
    if ((Test-Path $workerLog) -and (Select-String -Path $workerLog -Pattern " ready\." -Quiet)) { Write-Ok "Worker ready (Celery, solo pool)" }
    else { Write-Warn "Worker not ready yet; see logs\worker.log" }
}

if (Test-PortListening 3000) { Write-Ok "Web already running on 3000" }
elseif ($Production) { Start-AppWindow "web" $Frontend "npm run build; if (`$LASTEXITCODE -eq 0) { npm run start }" }
else { Start-AppWindow "web" $Frontend "npm run dev" }

Wait-Port 8000 "API"
Wait-Port 3000 "Web" 180

Write-Host ""
Write-Host "CareLedger is running" -ForegroundColor Green
Write-Host "  Web:      http://localhost:3000"
Write-Host "  API docs: http://localhost:8000/api/docs"
Write-Host "  Logs:     logs\api.log, logs\worker.log, logs\web.log"
Write-Host "  Stop:     .\scripts\dev.ps1 -Stop"
Write-Host "  Demo users (one shared password): docs\DEMO_USERS.md"
