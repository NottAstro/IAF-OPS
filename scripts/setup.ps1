# iaf-airops setup on Windows (ARCHITECTURE D32). Mirrors `make setup db pipeline seed` from the Makefile.
# Needs: Docker Desktop (for PostGIS), Node 24, and uv (https://docs.astral.sh/uv/) or Python 3.12.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1            # everything
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -SkipGis   # reuse existing boundaries (fast reseed)
param([switch]$SkipGis, [switch]$Restore)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ })
    (Get-Content .env) -replace '^JWT_SECRET=.*', "JWT_SECRET=$secret" | Set-Content .env -Encoding utf8
    Write-Host "created .env (add OWM_API_KEY / OpenSky credentials there if you have them)"
}

Write-Host "1/5 Python 3.12 virtualenv + backend packages"
if (-not (Test-Path .venv\Scripts\python.exe)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) { uv venv .venv --python 3.12 } else { py -3.12 -m venv .venv }
}
if (Get-Command uv -ErrorAction SilentlyContinue) { uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt }
else { .venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt }

Write-Host "2/5 npm packages (frontend, wind sidecar)"
Push-Location frontend; npm ci --no-audit --no-fund; Pop-Location
Push-Location wind; npm ci --no-audit --no-fund; Pop-Location

Write-Host "3/5 PostGIS in Docker"
docker compose up -d db | Out-Null
for ($i = 0; $i -lt 40; $i++) {
    if ((docker inspect -f '{{.State.Health.Status}}' iaf-airops-db 2>$null) -eq "healthy") { break }
    Start-Sleep -Seconds 3
}
Push-Location backend; ..\.venv\Scripts\python.exe -m app.init_db; Pop-Location

if ($Restore) {
    Write-Host "4/5 restore data\dumps\airops.dump (skips the GIS pipeline and the seed)"
    docker exec iaf-airops-db pg_restore -U airops -d airops --clean --if-exists --no-owner /dumps/airops.dump
    Write-Host "done. Start the app with scripts\dev.ps1"
    exit 0
}
if (-not $SkipGis) {
    Write-Host "4/5 GIS pipeline: official boundaries, places, airports (~5 min, downloads ~70 MB)"
    .venv\Scripts\python.exe pipeline\run_pipeline.py
}
Write-Host "5/5 synthetic data (inventory, history, Phase 2 missions / zones / forecast)"
Push-Location backend; ..\.venv\Scripts\python.exe -m generator; Pop-Location
Write-Host "done. Start the app with scripts\dev.ps1 (OSM roads / rail are optional: python pipeline\osm.py needs osmium)"
