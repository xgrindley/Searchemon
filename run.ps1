# Opens the monitor window (no console). Monitoring runs while the window is open.
# Add -Headless to run in this console instead.
param([switch]$Headless)
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Run setup first:  powershell -ExecutionPolicy Bypass -File .\setup.ps1" -ForegroundColor Red
    exit 1
}

& $python -c "import yaml, requests, playwright, zipcodes" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Setup is not finished (some packages are missing). Run:" -ForegroundColor Red
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\setup.ps1"
    exit 1
}

if ($Headless) {
    & $python app.py --headless
    exit $LASTEXITCODE
}

$p = Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "app.py" -WorkingDirectory $PSScriptRoot -PassThru
Write-Host "Starting the monitor. Its window opens in a few seconds."
Start-Sleep -Seconds 5
if ($p.HasExited) {
    Write-Host "The app closed right after starting. Showing the error:" -ForegroundColor Red
    & $python app.py --headless
} else {
    Write-Host "Running. Control panel: http://127.0.0.1:8765" -ForegroundColor Green
}
