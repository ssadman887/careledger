<#
.SYNOPSIS
  Apply migrations and load the deterministic, idempotent demo seed (safe to re-run).

.PARAMETER Reset
  Start from an empty database: drop, recreate and migrate it, then seed. Use after demos or
  E2E runs to get the original demo data back. Development only.
#>
param([switch]$Reset)
. (Join-Path $PSScriptRoot "common.ps1")

Assert-Postgres
Push-Location $Backend
try {
    if ($Reset) {
        Invoke-Checked "reset and seed" { & $VenvPython -m seed --reset }
    } else {
        Invoke-Checked "alembic upgrade" { & $VenvPython -m alembic upgrade head }
        Invoke-Checked "seed" { & $VenvPython -m seed }
    }
} finally { Pop-Location }
