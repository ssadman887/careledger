<#
.SYNOPSIS
  Run CareLedger's checks natively: lint, types and tests for backend and frontend.

.PARAMETER E2E
  Also run the Playwright E2E tests (the stack must be running: .\scripts\dev.ps1).

.PARAMETER Fast
  Skip lint and type checks; run tests only.
#>
param([switch]$E2E, [switch]$Fast)

. (Join-Path $PSScriptRoot "common.ps1")

Assert-Postgres
Push-Location $Backend
try {
    if (-not $Fast) {
        Write-Step "Backend: ruff + mypy"
        Invoke-Checked "ruff check" { & $VenvPython -m ruff check . }
        Invoke-Checked "ruff format" { & $VenvPython -m ruff format --check . }
        Invoke-Checked "mypy" { & $VenvPython -m mypy }
    }
    Write-Step "Backend: pytest (uses database careledger_test)"
    Invoke-Checked "pytest" { & $VenvPython -m pytest --cov --cov-report=term-missing:skip-covered }
    if (-not $Fast) {
        Write-Step "Backend: migrations match models"
        $env:DATABASE_URL = "postgresql+psycopg://careledger:careledger@localhost:5432/careledger_test"
        try { Invoke-Checked "alembic check" { & $VenvPython -m alembic check } } finally { Remove-Item Env:DATABASE_URL }
    }
} finally { Pop-Location }

Push-Location $Frontend
try {
    if (-not $Fast) {
        Write-Step "Frontend: eslint + prettier + tsc"
        Invoke-Checked "eslint" { npm run -s lint }
        Invoke-Checked "prettier" { npm run -s format:check }
        Invoke-Checked "tsc" { npm run -s typecheck }
    }
    Write-Step "Frontend: vitest"
    Invoke-Checked "vitest" { npm test }
    if ($E2E) {
        Write-Step "Frontend: playwright (needs the running stack)"
        Invoke-Checked "playwright" { npx playwright test }
    }
} finally { Pop-Location }

Write-Host ""
Write-Host "All checks passed." -ForegroundColor Green
