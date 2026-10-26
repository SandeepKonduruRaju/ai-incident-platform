<#
.SYNOPSIS
  Runs one k6 scenario against the local compose stack and collects the server-side numbers (milestone 4).

.EXAMPLE
  .\loadtest\run.ps1 -Script api-mix.js -Name a-api-mix
  .\loadtest\run.ps1 -Script e2e.js -Name b-e2e -K6Env @{ RATE = "30" }

  Prerequisites (see loadtest/README.md): the stack is up with the observability profile and the dev profile,
  and the rate limit is raised for load tests (otherwise most creations are 429 by design).
  Writes loadtest/results/<Name>.json (k6 summary), <Name>.prom.json (Prometheus) and <Name>.docker-stats.csv.
#>
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][string]$Name,
    [hashtable]$K6Env = @{},
    [string]$Network = "incident-service_default",
    [string]$K6Image = "grafana/k6:2.2.0"
)
# Not "Stop": Windows PowerShell 5.1 turns any stderr line of a native command (docker's pull progress, k6's
# progress) into a terminating error. Failures are checked through exit codes instead.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
docker image inspect $K6Image *> $null
if ($LASTEXITCODE -ne 0) { docker pull $K6Image | Out-Null }
$results = Join-Path $root "results"
New-Item -ItemType Directory -Force $results | Out-Null

# CPU/memory of every container every 5 s while k6 runs (the first saturated container is the bottleneck).
$statsFile = Join-Path $results "$Name.docker-stats.csv"
"time,container,cpu,mem" | Out-File -Encoding utf8 $statsFile
$sampler = Start-Job -ArgumentList $statsFile -ScriptBlock {
    param($file)
    while ($true) {
        $now = (Get-Date).ToUniversalTime().ToString("HH:mm:ss")
        docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" |
            ForEach-Object { "$now,$_" } | Out-File -Append -Encoding utf8 $file
        Start-Sleep -Seconds 5
    }
}

$envArgs = @("-e", "RESULT_NAME=$Name")
foreach ($key in $K6Env.Keys) { $envArgs += @("-e", "$key=$($K6Env[$key])") }

$start = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
try {
    docker run --rm --network $Network `
        -v "${root}:/scripts:ro" -v "${results}:/results" `
        @envArgs $K6Image run --quiet "/scripts/$Script"
    $k6Exit = $LASTEXITCODE   # 99 = a threshold failed (still a valid measurement)
} finally {
    Stop-Job $sampler; Remove-Job $sampler
}
$end = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

Start-Sleep -Seconds 20   # one more Prometheus scrape (15 s interval) after the run
python (Join-Path $root "prom_report.py") --start $start --end $end --out (Join-Path $results "$Name.prom.json")
"k6 exit code: $k6Exit  (0 = all thresholds passed, 99 = some threshold failed)"
