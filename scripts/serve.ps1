<#
.SYNOPSIS
  Build the frontend if needed and start Paper Atlas, locally or publicly via a Cloudflare quick tunnel.

.EXAMPLE
  .\scripts\serve.ps1            # local only: http://127.0.0.1:8000
.EXAMPLE
  .\scripts\serve.ps1 -Public    # access-gated app + admin console + trycloudflare URL
#>
param(
    [switch]$Public,
    [int]$Port = 8000,
    [int]$AdminPort = 8001,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
. (Join-Path $PSScriptRoot 'activate.ps1')
$venvPython = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts/python.exe'

# --- frontend build (only when sources are newer than dist) ---------------------
if (-not $SkipBuild) {
    $dist = Join-Path $root 'frontend/dist/index.html'
    $newestSrc = Get-ChildItem (Join-Path $root 'frontend') -Recurse -File -Include *.ts,*.tsx,*.css,*.html |
        Where-Object { $_.FullName -notmatch '\\(node_modules|dist)\\' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not (Test-Path $dist) -or $newestSrc.LastWriteTime -gt (Get-Item $dist).LastWriteTime) {
        Write-Host 'Building frontend...' -ForegroundColor Cyan
        Push-Location (Join-Path $root 'frontend')
        if (-not (Test-Path node_modules)) { npm install --no-audit --no-fund }
        npm run build
        if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Frontend build failed' }
        Pop-Location
    }
}

# --- API server ------------------------------------------------------------------
$uv = Get-Command uv -ErrorAction SilentlyContinue
$apiArgs = @('-m', 'paper_rag.api', '--port', $Port, '--admin-port', $AdminPort)
if ($Public) { $apiArgs += '--public' }

if (-not $Public) {
    if ($uv) { & uv run python @apiArgs } else { & $venvPython @apiArgs }
    exit $LASTEXITCODE
}

$python = if ($uv) { 'uv' } else { $venvPython }
$pyArgs = if ($uv) { @('run', 'python') + $apiArgs } else { $apiArgs }
$server = Start-Process -FilePath $python -ArgumentList $pyArgs -NoNewWindow -PassThru

# --- Cloudflare quick tunnel (app port only; the admin port is never exposed) ----
$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    Write-Warning 'cloudflared not found. Install it with: winget install --id Cloudflare.cloudflared'
    Write-Warning "The server is running locally on http://127.0.0.1:$Port (Ctrl+C to stop)."
    Wait-Process -Id $server.Id
    exit
}
Start-Sleep -Seconds 3
Write-Host "Starting Cloudflare quick tunnel -> http://localhost:$Port" -ForegroundColor Cyan
Write-Host 'Look for the https://*.trycloudflare.com URL below. Share it; approve visitors in the admin console.' -ForegroundColor Cyan
try {
    & $cloudflared.Source tunnel --no-autoupdate --url "http://localhost:$Port"
}
finally {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
