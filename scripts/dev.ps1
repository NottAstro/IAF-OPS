# Start the stack on Windows: PostGIS (Docker) + wind sidecar (8787) + API (API_PORT, default 8010) + web (5173).
# Mirrors scripts/dev.sh. Ctrl-C stops the three processes; the database container keeps running.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$port = ((Get-Content .env | Where-Object { $_ -match '^API_PORT=' }) -replace '^API_PORT=', '' -split '\s')[0]
if (-not $port) { $port = 8010 }
New-Item -ItemType Directory -Force data\logs | Out-Null

$busy = @(8787, [int]$port, 5173) | Where-Object { Get-NetTCPConnection -State Listen -LocalPort $_ -ErrorAction SilentlyContinue }
if ($busy) { Write-Host "Port(s) already in use: $($busy -join ', '). iaf-airops is probably running: http://localhost:5173"; exit 1 }

docker compose up -d db | Out-Null
for ($i = 0; $i -lt 40; $i++) {
    if ((docker inspect -f '{{.State.Health.Status}}' iaf-airops-db 2>$null) -eq "healthy") { break }
    Start-Sleep -Seconds 2
}

$procs = @()
$procs += Start-Process node -ArgumentList "server.mjs" -WorkingDirectory "$root\wind" -NoNewWindow -PassThru `
    -RedirectStandardOutput "$root\data\logs\wind.log" -RedirectStandardError "$root\data\logs\wind.err.log"
$procs += Start-Process "$root\.venv\Scripts\python.exe" -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port $port --workers 1" `
    -WorkingDirectory "$root\backend" -NoNewWindow -PassThru -RedirectStandardOutput "$root\data\logs\api.log" -RedirectStandardError "$root\data\logs\api.err.log"
$procs += Start-Process "cmd.exe" -ArgumentList "/c npx vite" -WorkingDirectory "$root\frontend" -NoNewWindow -PassThru `
    -RedirectStandardOutput "$root\data\logs\web.log" -RedirectStandardError "$root\data\logs\web.err.log"

Start-Sleep -Seconds 8
foreach ($svc in @(@("wind", 8787), @("api", $port), @("web", 5173))) {
    if (Get-NetTCPConnection -State Listen -LocalPort $svc[1] -ErrorAction SilentlyContinue) { Write-Host ("  ok  {0,-4} http://localhost:{1}" -f $svc[0], $svc[1]) }
    else { Write-Host ("  --  {0,-4} did not start: see data\logs\{0}*.log" -f $svc[0]) }
}
Write-Host "`nOpen http://localhost:5173   (logs in data\logs, Ctrl-C to stop)"
try { Wait-Process -Id ($procs | ForEach-Object Id) } finally { $procs | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } }
