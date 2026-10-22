param([ValidateSet('init','up','down','logs')][string]$Action = 'up')
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
switch ($Action) {
  'init' { docker run --rm -v "${PWD}:/workspace" -w /workspace python:3.12-slim python scripts/docker_setup.py }
  'up' { docker compose up --build -d --wait --wait-timeout 600 }
  'down' { docker compose down }
  'logs' { docker compose logs -f --tail 100 }
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
