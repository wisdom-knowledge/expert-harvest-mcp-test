# Install this expert-harvest skill package on Windows.
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 [-DestRoot <dir>]
param(
  [string]$DestRoot = $(if ($env:EH_SKILL_HOME) { $env:EH_SKILL_HOME } else { Join-Path $env:USERPROFILE ".agents\skills" })
)

$ErrorActionPreference = "Stop"
$flowId = "function-files-pack"
$src = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $src "SKILL.md"))) {
  throw "SKILL.md missing in $src"
}
$dest = Join-Path $DestRoot $flowId
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path (Join-Path $src "*") -Destination $dest -Recurse -Force
Set-Content -Path (Join-Path $dest ".installed-path") -Value $dest -Encoding utf8

Write-Output "installed $flowId"
Write-Output "path=$dest"
Write-Output "entry=$(Join-Path $dest 'SKILL.md')"
Write-Output "run=$(Join-Path $dest 'scripts\run.ps1')"
