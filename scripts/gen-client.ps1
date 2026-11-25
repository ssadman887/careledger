<#
.SYNOPSIS
  Export FastAPI's OpenAPI spec and regenerate the typed TypeScript client.
#>
. (Join-Path $PSScriptRoot "common.ps1")

Push-Location $Backend
try { Invoke-Checked "export openapi" { & $VenvPython -m app.export_openapi (Join-Path $Frontend "openapi.json") } }
finally { Pop-Location }
Push-Location $Frontend
try { Invoke-Checked "openapi-typescript" { npm run -s gen:client } } finally { Pop-Location }
