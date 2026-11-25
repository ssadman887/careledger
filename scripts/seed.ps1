<#
.SYNOPSIS
  Apply migrations and load the deterministic, idempotent demo seed (safe to re-run).
#>
. (Join-Path $PSScriptRoot "common.ps1")

Assert-Postgres
Push-Location $Backend
try {
    Invoke-Checked "alembic upgrade" { & $VenvPython -m alembic upgrade head }
    Invoke-Checked "seed" { & $VenvPython -m seed }
} finally { Pop-Location }
