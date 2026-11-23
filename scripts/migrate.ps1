# Bootstrap roles/database/extensions and apply Alembic migrations (Windows).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")
$py = if (Test-Path ..\.venv\Scripts\python.exe) { "..\.venv\Scripts\python.exe" } else { "python" }
& $py -m app.database.bootstrap
& $py -m alembic upgrade head
& $py -m alembic current
