# Opens the monitor window (no console). Monitoring runs while the window is open.
# Add -Headless to run in this console instead.
# Add -Update to install the newest stable release first (-Update -Channel test for the newest test build).
# Your settings and data are never touched, and a snapshot is saved first (.\versions.ps1 restore undoes it).
param([switch]$Headless, [switch]$Update, [string]$Channel = "stable")
Set-Location $PSScriptRoot

if ($Update) {
    Write-Host "Checking for the newest $Channel version ..."
    & powershell -ExecutionPolicy Bypass -File .\update.ps1 -Channel $Channel
    if ($LASTEXITCODE -ne 0) {
        Write-Host "The update did not finish, so the current version will start." -ForegroundColor Yellow
    } else {
        Write-Host "If packages changed in this update, run setup.ps1 once." -ForegroundColor Yellow
    }
}

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
