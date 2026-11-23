# Local development setup (Windows PowerShell). Requires Python 3.12+ and Docker Desktop.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r backend\requirements-dev.txt
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env; Write-Host "Created backend\.env - edit secrets before use." }
Write-Host "Setup complete. Next: .\scripts\start.ps1 (Docker) or .\scripts\migrate.ps1"
