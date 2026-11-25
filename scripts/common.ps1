# Shared helpers for the native (no Docker) Windows dev scripts. Dot-source, do not run.
# Compatible with Windows PowerShell 5.1 and PowerShell 7.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
$PgBin = "C:\Program Files\PostgreSQL\16\bin"

# Make freshly installed tools visible without restarting the shell.
foreach ($dir in @("C:\Program Files\nodejs", $PgBin, (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"))) {
    if ((Test-Path $dir) -and ($env:Path -notlike "*$dir*")) { $env:Path = "$dir;$env:Path" }
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "    $Message" -ForegroundColor Yellow }

function Read-DotEnv {
    # Returns the root .env as a hashtable (KEY=VALUE lines; comments ignored).
    $values = @{}
    $path = Join-Path $Root ".env"
    if (Test-Path $path) {
        foreach ($line in Get-Content $path) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $values[$Matches[1]] = $Matches[2] }
        }
    }
    return $values
}

function Test-PortListening([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Port([int]$Port, [string]$Name, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening $Port) { Write-Ok "$Name is listening on $Port"; return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not start on port $Port within $Seconds s"
}

function Find-Garnet {
    $cmd = Get-Command GarnetServer -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $pkg = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Directory -Filter "Microsoft.Garnet*" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pkg) {
        $exe = Get-ChildItem $pkg.FullName -Recurse -Filter "GarnetServer.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($exe) { return $exe.FullName }
    }
    return $null
}

function Start-Garnet {
    if (Test-PortListening 6379) { Write-Ok "Redis-compatible server already on 6379"; return }
    $garnet = Find-Garnet
    if (-not $garnet) { throw "Garnet not found. Install it with: winget install -e --id Microsoft.Garnet.DN8" }
    Start-Process -FilePath $garnet -ArgumentList "--bind", "127.0.0.1", "--port", "6379" -WindowStyle Minimized | Out-Null
    Wait-Port 6379 "Garnet (Redis)"
}

function Assert-Postgres {
    $svc = Get-Service -Name "postgresql-x64-16" -ErrorAction SilentlyContinue
    if (-not $svc) { throw "PostgreSQL 16 service not found. Install it with: winget install -e --id PostgreSQL.PostgreSQL.16" }
    if ($svc.Status -ne "Running") {
        Write-Warn "PostgreSQL service is $($svc.Status); starting it (may need an admin shell)"
        Start-Service -Name "postgresql-x64-16"
    }
    Wait-Port 5432 "PostgreSQL" 30
}

function Invoke-Checked([string]$What, [scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}
