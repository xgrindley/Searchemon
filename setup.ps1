# One-time setup: creates a private Python environment and installs dependencies.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Python versions the packages ship ready-made installs for, best first.
# Brand-new Python releases (like 3.15) often lack them for months, and then
# pip tries to compile packages, which fails on a normal Windows PC.
$Supported = @("3.13", "3.12", "3.14", "3.11")

function Fail($msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    exit 1
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Fail ("Python not found. Install Python 3.13 with:`n`n    winget install -e --id Python.Python.3.13`n`n" +
          "or from python.org (tick 'Add python.exe to PATH'). Then close PowerShell, open a new one and rerun setup.")
}

# Find the best installed Python the packages support.
$ErrorActionPreference = "Continue"
$pick = $null
foreach ($v in $Supported) {
    & py "-$v" -c "import sys" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pick = $v; break }
}
$have = (& py -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null | Out-String).Trim()
$ErrorActionPreference = "Stop"
if (-not $pick) {
    if (-not $have) { $have = "unknown" }
    Fail ("Installed Python: $have. This app needs Python 3.11 to 3.14 (3.13 recommended), because newer`n" +
          "versions don't have ready-made installs of its packages yet. Install 3.13 alongside what you have:`n`n" +
          "    winget install -e --id Python.Python.3.13`n`n" +
          "or download it from python.org. Then close PowerShell, open a new one and rerun setup.")
}
Write-Host "Using Python $pick"

# Rebuild the environment if it was made with a different Python version.
if (Test-Path ".venv\pyvenv.cfg") {
    $cfg = Get-Content ".venv\pyvenv.cfg" -Raw
    if ($cfg -notmatch "(?m)^version\w*\s*=\s*$([regex]::Escape($pick))\.") {
        Write-Host "Rebuilding the environment for Python $pick..."
        Remove-Item ".venv" -Recurse -Force
    }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    & py "-$pick" -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the environment with Python $pick." }
}

$python = ".\.venv\Scripts\python.exe"
Write-Host "Installing packages (this can take a few minutes)..."
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Fail "Package install failed (see the messages above). Check your internet connection and rerun setup."
}

& $python -c "import yaml, requests, playwright, zipcodes"
if ($LASTEXITCODE -ne 0) { Fail "Packages did not install correctly. Rerun setup." }

# Browser checks use Microsoft Edge, which comes with Windows, so no browser download is needed.
if (-not (Test-Path "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") -and
    -not (Test-Path "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")) {
    Write-Host "Edge not found; installing a private Chromium for browser checks..."
    & $python -m playwright install chromium
}

if (-not (Test-Path "config.yaml")) {
    Copy-Item "config.example.yaml" "config.yaml"
    Write-Host "Created config.yaml. Add your Discord webhook and ZIP in the control panel." -ForegroundColor Yellow
}

Write-Host "Setup complete. Start the app with .\run.ps1" -ForegroundColor Green
