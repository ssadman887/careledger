<#
.SYNOPSIS
  One-time native setup for CareLedger on Windows (no Docker).

.DESCRIPTION
  Prerequisites (install once with winget):
    winget install -e --id Python.Python.3.12
    winget install -e --id OpenJS.NodeJS.LTS
    winget install -e --id PostgreSQL.PostgreSQL.16
    winget install -e --id Microsoft.Garnet.DN8
  Then: creates backend\.venv, installs Python + Node dependencies, creates the careledger
  database role and databases, applies migrations and seeds demo data. Safe to re-run.

.PARAMETER SkipBrowsers
  Do not download Playwright's Chromium (only needed for E2E tests).
#>
param([switch]$SkipBrowsers)

. (Join-Path $PSScriptRoot "common.ps1")

Write-Step "Checking prerequisites"
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { throw "Python launcher 'py' not found. Install Python 3.12." }
& py -3.12 --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 not found. winget install -e --id Python.Python.3.12" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js not found. winget install -e --id OpenJS.NodeJS.LTS" }
Assert-Postgres
if (-not (Find-Garnet)) { throw "Garnet not found. winget install -e --id Microsoft.Garnet.DN8" }
Write-Ok "Python 3.12, Node, PostgreSQL 16 and Garnet found"

Write-Step "Environment file"
$envPath = Join-Path $Root ".env"
if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $Root ".env.example") $envPath
    Write-Ok "Created .env from .env.example"
} else { Write-Ok ".env exists" }
$dotenv = Read-DotEnv

Write-Step "Python virtual environment (backend\.venv)"
if (-not (Test-Path $VenvPython)) { Invoke-Checked "venv" { py -3.12 -m venv (Join-Path $Backend ".venv") } }
Invoke-Checked "pip upgrade" { & $VenvPython -m pip install -q --upgrade pip }
Invoke-Checked "pip install" { & $VenvPython -m pip install -q -e "$Backend[dev]" }
Write-Ok "Backend dependencies installed into the venv"

Write-Step "Frontend dependencies"
Push-Location $Frontend
try {
    Invoke-Checked "npm ci" { npm ci --no-audit --no-fund --loglevel=error }
    if (-not $SkipBrowsers) { Invoke-Checked "playwright install" { npx playwright install chromium } }
} finally { Pop-Location }
Write-Ok "node_modules ready"

Write-Step "Database role and databases"
$superPw = $dotenv["POSTGRES_SUPERUSER_PASSWORD"]
if (-not $superPw) {
    Write-Warn "POSTGRES_SUPERUSER_PASSWORD is not in .env; psql will prompt for the 'postgres' password"
} else { $env:PGPASSWORD = $superPw }
$sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'careledger') THEN
    CREATE ROLE careledger LOGIN PASSWORD 'careledger' CREATEDB;
  END IF;
END `$`$;
SELECT 'CREATE DATABASE careledger OWNER careledger'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'careledger')\gexec
"@
try {
    Invoke-Checked "create role/database" { $sql | & (Join-Path $PgBin "psql.exe") -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -q }
} finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
Write-Ok "Role 'careledger' and database 'careledger' ready"

Write-Step "Migrations and seed"
Push-Location $Backend
try {
    Invoke-Checked "alembic upgrade" { & $VenvPython -m alembic upgrade head }
    Invoke-Checked "seed" { & $VenvPython -m seed }
} finally { Pop-Location }

Write-Host ""
Write-Host "Setup complete. Start everything with:  .\scripts\dev.ps1" -ForegroundColor Green
Write-Host "Demo users (one shared password) are listed in docs\DEMO_USERS.md"
