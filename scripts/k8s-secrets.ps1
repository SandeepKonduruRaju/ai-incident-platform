<#
.SYNOPSIS
  Creates the Kubernetes Secrets of ai-incident-platform from the local .env files (section 3.5).

.DESCRIPTION
  Reads ONLY the keys the cluster needs from incident-service/.env and investigation-worker/.env.
  A key that is missing (or still a CHANGE_ME placeholder) gets a random value: fine for a local cluster.
  Values never appear in output, on a command line or in the repo: they go through a temporary env file
  that is removed right after "kubectl apply". Existing Secrets are kept (the Postgres volume was
  initialised with that password) unless -Rotate is given.

.PARAMETER Rotate
  Replace existing Secrets. The database password then no longer matches an existing Postgres volume:
  only use it on a fresh cluster (or after scripts/k8s-down.ps1).

.PARAMETER WithAnthropicKey
  Also put ANTHROPIC_API_KEY (from investigation-worker/.env) into worker-secrets, for LLM_PROVIDER=anthropic.
  Not needed for the default fake LLM.
#>
param(
    [string]$Namespace = "incident-platform",
    [switch]$Rotate,
    [switch]$WithAnthropicKey
)
# Native tools (kind, kubectl, docker) write progress and expected "not found" messages to stderr; Windows
# PowerShell 5.1 would turn those into terminating errors under "Stop". Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

function Read-DotEnv([string]$Path) {
    $values = @{}
    if (-not (Test-Path $Path)) { return $values }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $value = $Matches[2]
            if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'") -and $value[-1] -eq $value[0]) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$Matches[1]] = $value
        }
    }
    return $values
}

function New-RandomValue([int]$Bytes = 24) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

# Returns @{ Value; Source } without ever printing the value.
function Get-Setting([hashtable[]]$Sources, [string]$Key, [int]$MinLength = 1) {
    foreach ($source in $Sources) {
        $value = $source[$Key]
        if ($value -and $value -notmatch 'CHANGE_ME' -and $value.Length -ge $MinLength) {
            return @{ Value = $value; Source = ".env" }
        }
    }
    return @{ Value = (New-RandomValue); Source = "generated" }
}

function Test-Secret([string]$Name) {
    & kubectl get secret $Name -n $Namespace -o name *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-SecretValue([string]$Name, [string]$Key) {
    $encoded = & kubectl get secret $Name -n $Namespace -o "jsonpath={.data.$Key}"
    return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded))
}

function Set-Secret([string]$Name, [hashtable]$Data) {
    $file = Join-Path ([System.IO.Path]::GetTempPath()) ("k8s-secret-" + [guid]::NewGuid() + ".env")
    try {
        $lines = $Data.Keys | Sort-Object | ForEach-Object { "$_=$($Data[$_])" }
        [System.IO.File]::WriteAllLines($file, [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
        & kubectl create secret generic $Name -n $Namespace "--from-env-file=$file" --dry-run=client -o yaml |
            & kubectl apply -f - | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "kubectl apply failed for secret $Name" }
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $file
    }
}

$names = "postgres-credentials", "incident-service-secrets", "worker-secrets"
$existing = @($names | Where-Object { Test-Secret $_ })
if ($existing.Count -eq $names.Count -and -not $Rotate) {
    Write-Host "Secrets already exist in $Namespace (kept; use -Rotate on a fresh cluster to replace them)."
    return
}

$serviceEnv = Read-DotEnv (Join-Path $root "incident-service/.env")
$workerEnv = Read-DotEnv (Join-Path $root "investigation-worker/.env")

# The Postgres volume keeps the password it was initialised with: reuse it unless rotating.
if ((Test-Secret "postgres-credentials") -and -not $Rotate) {
    $db = @{ Value = (Get-SecretValue "postgres-credentials" "POSTGRES_PASSWORD"); Source = "existing secret" }
} else {
    $db = Get-Setting @($serviceEnv) "DB_PASSWORD"
}
$jwt = Get-Setting @($serviceEnv) "JWT_SECRET" 32
$token = Get-Setting @($serviceEnv, $workerEnv) "INTERNAL_API_TOKEN" 16
$databaseUrl = "postgresql+asyncpg://incident_app:" + [uri]::EscapeDataString($db.Value) + "@postgres:5432/incident_platform"

Set-Secret "postgres-credentials" @{ POSTGRES_PASSWORD = $db.Value }
Set-Secret "incident-service-secrets" @{ DB_PASSWORD = $db.Value; JWT_SECRET = $jwt.Value; INTERNAL_API_TOKEN = $token.Value }
$workerData = @{ DATABASE_URL = $databaseUrl; INTERNAL_API_TOKEN = $token.Value }
if ($WithAnthropicKey) {
    if (-not $workerEnv["ANTHROPIC_API_KEY"]) { throw "-WithAnthropicKey: ANTHROPIC_API_KEY is not set in investigation-worker/.env" }
    $workerData["ANTHROPIC_API_KEY"] = $workerEnv["ANTHROPIC_API_KEY"]
}
Set-Secret "worker-secrets" $workerData

# Names and sources only, never values.
Write-Host "Secrets created in ${Namespace}:"
Write-Host "  postgres-credentials      POSTGRES_PASSWORD ($($db.Source))"
Write-Host "  incident-service-secrets  DB_PASSWORD ($($db.Source)), JWT_SECRET ($($jwt.Source)), INTERNAL_API_TOKEN ($($token.Source))"
$anthropic = ""
if ($WithAnthropicKey) { $anthropic = ", ANTHROPIC_API_KEY (.env)" }
Write-Host "  worker-secrets            DATABASE_URL (from DB_PASSWORD), INTERNAL_API_TOKEN ($($token.Source))$anthropic"
