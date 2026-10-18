# `make check` on Windows: backend tests (needs a seeded database) + classifier self-check + frontend typecheck + unit tests.
# Stop scripts\dev.ps1 first: the running simulator writes to the same database and makes the planner tests flaky.
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"
..\.venv\Scripts\python.exe -m app.live.classify
if ($LASTEXITCODE) { exit $LASTEXITCODE }
..\.venv\Scripts\python.exe -m pytest -q tests -p no:warnings
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Pop-Location
Push-Location "$root\frontend"
npx tsc -b
if ($LASTEXITCODE) { exit $LASTEXITCODE }
npx vitest run
$code = $LASTEXITCODE
Pop-Location
exit $code
