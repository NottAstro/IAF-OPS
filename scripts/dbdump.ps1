# Dump the seeded database (GIS tables included) to data\dumps\airops.dump so a teammate can skip the GIS pipeline:
#   powershell -ExecutionPolicy Bypass -File scripts\dbdump.ps1          # on the machine that has the data
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Restore  # on the new machine (after copying the file)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force "$root\data\dumps" | Out-Null
docker exec iaf-airops-db pg_dump -U airops -d airops -Fc -f /dumps/airops.dump
Write-Host "wrote data\dumps\airops.dump ($([math]::Round((Get-Item "$root\data\dumps\airops.dump").Length / 1MB, 1)) MB)"
