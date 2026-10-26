<#
.SYNOPSIS
  Scenario (d), fair cache on/off comparison: for each mode, recreate incident-service with REDIS_CACHE_ENABLED,
  warm the JVM with a short read-only run (JIT warm-up otherwise competes for CPU with the measurement), then
  measure cache.js at -Rate req/s. Run from the repo root with the stack up (see loadtest/README.md).
#>
param([string]$Rate = "20")
$ErrorActionPreference = "Continue"
$repo = Split-Path $PSScriptRoot -Parent

foreach ($mode in @("on", "off")) {
    Push-Location (Join-Path $repo "incident-service")
    $env:REDIS_CACHE_ENABLED = if ($mode -eq "on") { "true" } else { "false" }
    docker compose up -d --no-deps incident-service 2>&1 | Out-Null
    do { Start-Sleep 10; $health = docker inspect -f '{{.State.Health.Status}}' incident-service } until ($health -eq 'healthy')
    Pop-Location
    & (Join-Path $PSScriptRoot "run.ps1") -Script cache.js -Name "warmup-$mode" -K6Env @{ RATE = $Rate; DURATION = "60s"; TENANTS = "2" } | Out-Null
    & (Join-Path $PSScriptRoot "run.ps1") -Script cache.js -Name "d-cache-$mode-$Rate" -K6Env @{ RATE = $Rate }
}
Remove-Item Env:REDIS_CACHE_ENABLED
Push-Location (Join-Path $repo "incident-service"); docker compose up -d --no-deps incident-service 2>&1 | Out-Null; Pop-Location
