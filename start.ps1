# DWH Code Review: backend (8000) ve frontend (5173) sunucularini ayri pencerelerde baslatir.
# Ilk calistirmada sanal ortami ve npm paketlerini kurar.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'app\backend'
$frontend = Join-Path $root 'app\frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'Python sanal ortami kuruluyor...'
    py -3.12 -m venv (Join-Path $backend '.venv')
    & $python -m pip install -q -r (Join-Path $backend 'requirements.txt')
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'npm paketleri kuruluyor...'
    npm --prefix $frontend install
}

Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$python' -m uvicorn app.main:app --port 8000"
Start-Process powershell -WorkingDirectory $frontend -ArgumentList '-NoExit', '-Command', 'npm run dev'
Start-Sleep -Seconds 4
Start-Process 'http://localhost:5173'
