<#
.SYNOPSIS
  GitOps on the local kind cluster (section 3.7): installs Argo CD (pinned) and the platform Application.

.DESCRIPTION
  1. Prepares the cluster without deploying the apps: scripts/k8s-up.ps1 -SkipApps (kind cluster, ingress-nginx,
     metrics-server, namespace, Secrets from the .env files). Idempotent.
  2. Installs Argo CD $ArgoCdVersion into the "argocd" namespace (official manifest, server-side apply) and
     waits until every component is ready.
  3. Applies k8s/argocd/project.yaml and k8s/argocd/application.yaml: from then on Argo CD deploys
     k8s/overlays/gitops from the main branch on GitHub and keeps the cluster in sync with it.
  Do not run scripts/k8s-up.ps1 (without -SkipApps) on the same cluster: both would manage the same resources.

.PARAMETER SkipApplication
  Install Argo CD only (e.g. before the gitops overlay is on main).
#>
param(
    [string]$ClusterName = "incident-platform",
    [switch]$SkipApplication
)
# Native tools write progress to stderr; exit codes are checked explicitly (see k8s-up.ps1).
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$argoCdVersion = "v3.5.6"

function Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Assert-Ok([string]$What) { if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" } }

Push-Location $root
try {
    Step "cluster, add-ons, namespace and secrets (k8s-up.ps1 -SkipApps)"
    & (Join-Path $PSScriptRoot "k8s-up.ps1") -ClusterName $ClusterName -SkipApps

    Step "Argo CD $argoCdVersion"
    kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f - | Out-Null; Assert-Ok "argocd namespace"
    # Server-side apply: the Argo CD CRDs are too large for the client-side last-applied annotation.
    kubectl apply -n argocd --server-side --force-conflicts -f "https://raw.githubusercontent.com/argoproj/argo-cd/$argoCdVersion/manifests/install.yaml" | Out-Null
    Assert-Ok "Argo CD install"
    foreach ($deployment in "argocd-redis", "argocd-repo-server", "argocd-server", "argocd-dex-server", "argocd-applicationset-controller", "argocd-notifications-controller") {
        kubectl -n argocd rollout status "deployment/$deployment" --timeout=300s; Assert-Ok $deployment
    }
    kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s; Assert-Ok "argocd-application-controller"

    if (-not $SkipApplication) {
        Step "Argo CD project and Application (main -> k8s/overlays/gitops)"
        kubectl apply -f k8s/argocd/project.yaml; Assert-Ok "AppProject"
        kubectl apply -f k8s/argocd/application.yaml; Assert-Ok "Application"
    }

    Step "ready"
    Write-Host "Argo CD UI:  kubectl -n argocd port-forward svc/argocd-server 8443:443   then open https://localhost:8443"
    Write-Host "             (self-signed certificate; user: admin)"
    Write-Host "Password:    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' |"
    Write-Host "               ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(`$_)) }"
    Write-Host "Status:      kubectl -n argocd get applications"
    Write-Host "API:         http://localhost/api/v1/health"
} finally {
    Pop-Location
}
