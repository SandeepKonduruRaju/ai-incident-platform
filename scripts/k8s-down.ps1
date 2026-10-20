<#
.SYNOPSIS
  Deletes the local kind cluster of ai-incident-platform (section 3.5): all pods, volumes and secrets in it.
  Images, the compose stack and its volumes are not touched. Safe to run when the cluster does not exist.
#>
param([string]$ClusterName = "incident-platform")
# Native tools (kind, kubectl, docker) write progress and expected "not found" messages to stderr; Windows
# PowerShell 5.1 would turn those into terminating errors under "Stop". Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"

if (@(kind get clusters) -contains $ClusterName) {
    kind delete cluster --name $ClusterName
    if ($LASTEXITCODE -ne 0) { throw "kind delete cluster failed" }
} else {
    Write-Host "No kind cluster named '$ClusterName'."
}
