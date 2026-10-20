<#
.SYNOPSIS
  Runs the whole ai-incident-platform stack on a local kind cluster (section 3.5). Idempotent: run it again
  after code changes to rebuild, reload and roll out the images.

.DESCRIPTION
  1. Creates the kind cluster from k8s/kind-config.yaml (if it does not exist yet).
  2. Installs ingress-nginx (kind provider manifest) and metrics-server (patched for kind), pinned versions.
  3. Builds both images tagged with the git short SHA ("<sha>-dirty-<time>" when the tree has uncommitted
     changes) and loads them into the kind nodes: no registry involved.
  4. Writes that tag into k8s/overlays/local/kustomization.yaml (the two newTag lines).
  5. Creates the Secrets from the .env files (scripts/k8s-secrets.ps1).
  6. kubectl apply -k k8s/overlays/local, then waits for everything to be ready.

.EXAMPLE
  .\scripts\k8s-up.ps1
  .\scripts\k8s-up.ps1 -SkipBuild -Tag 6b5470c    # reuse images already built with that tag
#>
param(
    [string]$ClusterName = "incident-platform",
    [string]$Tag,
    [switch]$SkipBuild
)
# Native tools (kind, kubectl, docker) write progress and expected "not found" messages to stderr; Windows
# PowerShell 5.1 would turn those into terminating errors under "Stop". Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$namespace = "incident-platform"
$ingressNginxVersion = "controller-v1.15.1"   # last ingress-nginx release (project retired; local use only)

function Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Assert-Ok([string]$What) { if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" } }

Push-Location $root
try {
    foreach ($tool in "docker", "kind", "kubectl", "git") {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH" }
    }

    Step "kind cluster '$ClusterName'"
    if (@(kind get clusters) -contains $ClusterName) {
        Write-Host "exists"
    } else {
        kind create cluster --config k8s/kind-config.yaml --name $ClusterName --wait 180s; Assert-Ok "kind create cluster"
    }
    kubectl config use-context "kind-$ClusterName" | Out-Null; Assert-Ok "kubectl config use-context"

    Step "ingress-nginx $ingressNginxVersion"
    kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/$ingressNginxVersion/deploy/static/provider/kind/deploy.yaml" | Out-Null
    Assert-Ok "ingress-nginx apply"
    kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=300s
    Assert-Ok "ingress-nginx ready"

    Step "metrics-server"
    kubectl apply -k k8s/addons/metrics-server | Out-Null; Assert-Ok "metrics-server apply"

    if (-not $Tag) {
        $Tag = (git rev-parse --short HEAD).Trim()
        if (git status --porcelain) { $Tag = "$Tag-dirty-" + (Get-Date -Format "MMddHHmm") }
    }
    if (-not $SkipBuild) {
        Step "building images :$Tag"
        $created = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        $revision = (git rev-parse HEAD).Trim()
        foreach ($image in "incident-service", "investigation-worker") {
            docker build -t "${image}:$Tag" --build-arg "REVISION=$revision" --build-arg "CREATED=$created" --build-arg "VERSION=$Tag" $image
            Assert-Ok "docker build $image"
        }
    }
    Step "loading images into kind"
    kind load docker-image "incident-service:$Tag" "investigation-worker:$Tag" --name $ClusterName; Assert-Ok "kind load"

    Step "image tag $Tag -> k8s/overlays/local/kustomization.yaml"
    $overlay = Join-Path $root "k8s/overlays/local/kustomization.yaml"
    $text = [System.IO.File]::ReadAllText($overlay) -replace '(?m)^(\s+newTag:\s*)\S+', "`${1}$Tag"
    [System.IO.File]::WriteAllText($overlay, $text, (New-Object System.Text.UTF8Encoding($false)))

    Step "namespace and secrets"
    kubectl apply -f k8s/base/namespace.yaml | Out-Null; Assert-Ok "namespace"
    & (Join-Path $PSScriptRoot "k8s-secrets.ps1") -Namespace $namespace

    Step "apply k8s/overlays/local"
    # Job specs are immutable (the image tag changes): remove finished runs; both jobs are idempotent.
    kubectl delete job kafka-topics worker-ingest -n $namespace --ignore-not-found | Out-Null
    kubectl apply -k k8s/overlays/local; Assert-Ok "kubectl apply -k"

    Step "waiting for rollouts"
    kubectl -n $namespace rollout status statefulset/postgres --timeout=300s; Assert-Ok "postgres"
    kubectl -n $namespace rollout status statefulset/kafka --timeout=300s; Assert-Ok "kafka"
    kubectl -n $namespace wait --for=condition=complete job/kafka-topics --timeout=300s; Assert-Ok "kafka-topics job"
    kubectl -n $namespace rollout status deployment/investigation-worker --timeout=600s; Assert-Ok "investigation-worker"
    kubectl -n $namespace rollout status deployment/incident-service --timeout=600s; Assert-Ok "incident-service"
    kubectl -n $namespace wait --for=condition=complete job/worker-ingest --timeout=600s; Assert-Ok "worker-ingest job"

    Step "ready"
    kubectl -n $namespace get pods -o wide
    Write-Host "`nAPI:  http://localhost/api/v1/health   (images :$Tag)"
} finally {
    Pop-Location
}
