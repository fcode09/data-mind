param([ValidateSet('api','mcp','worker','voice','web')][string]$Service = 'api', [Parameter(ValueFromRemainingArguments=$true)][string[]]$ServiceArgs)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path '.env') {
  Get-Content '.env' | ForEach-Object {
    if ($_ -match '^([A-Z_]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
  }
}
switch ($Service) {
  'api' { go run ./apps/api @ServiceArgs }
  'mcp' { go run ./apps/mcp @ServiceArgs }
  'worker' { go run ./apps/worker @ServiceArgs }
  'voice' { python -m uvicorn apps.voice.main:app --host 127.0.0.1 --port 8102 }
  'web' { Set-Location apps/web; npm run dev -- --host 127.0.0.1 }
}
