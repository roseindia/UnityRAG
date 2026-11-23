# start.ps1          -> Docker Compose stack
# start.ps1 -Local   -> API + worker + scheduler from the virtualenv (Celery uses the 'solo' pool on Windows)
param([switch]$Local)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($Local) {
  Set-Location backend
  $venv = "..\.venv\Scripts"
  Start-Process -NoNewWindow "$venv\celery.exe" "-A app.workers.celery_app worker -Q ingestion,maintenance --pool=solo --loglevel=INFO"
  Start-Process -NoNewWindow "$venv\celery.exe" "-A app.workers.celery_app beat --loglevel=INFO"
  & "$venv\uvicorn.exe" app.main:app --reload --host 0.0.0.0 --port 8000
} else {
  if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
  docker compose up -d --build
  Write-Host "API: http://localhost:8000/docs   (via Nginx: http://localhost:8080)"
  Write-Host "First platform admin: docker compose exec api python -m app.cli create-platform-admin --email you@example.com"
}
