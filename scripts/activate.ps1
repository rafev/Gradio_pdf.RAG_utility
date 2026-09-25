<#
.SYNOPSIS
  Point uv at the Paper Atlas venv kept outside the repo, and activate it in this shell.

.DESCRIPTION
  The venv and .env live in $env:PAPER_ATLAS_ENV_ROOT
  (default C:\project_envs\Paper_Atlas), not in the repo. Run it once per shell; after that,
  `uv sync`, `uv run ...` and plain `python` all use that venv, and paper_rag.config reads the
  .env sitting next to it.

.EXAMPLE
  . .\scripts\activate.ps1
#>
$envRoot = if ($env:PAPER_ATLAS_ENV_ROOT) { $env:PAPER_ATLAS_ENV_ROOT } else { 'C:\project_envs\Paper_Atlas' }
$venv = Join-Path $envRoot '.venv'

$env:UV_PROJECT_ENVIRONMENT = $venv

$activate = Join-Path $venv 'Scripts\Activate.ps1'
if (Test-Path $activate) {
    . $activate
} else {
    Write-Warning "No venv at $venv yet. Create it with: uv sync --extra dev"
}
if (-not (Test-Path (Join-Path $envRoot '.env'))) {
    Write-Warning "No .env in $envRoot. Copy .env.example there and set ANTHROPIC_API_KEY."
}
