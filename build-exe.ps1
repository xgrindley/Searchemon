# Optional: builds a single PokeRestock.exe in .\dist so you can run it without PowerShell.
# Keep config.yaml in the same folder as the .exe.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

& .\.venv\Scripts\python.exe -m pip install pyinstaller --quiet
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed `
    --name PokeRestock --collect-submodules winotify --collect-all playwright app.py

Copy-Item "config.example.yaml" "dist\config.example.yaml" -Force
if (Test-Path "config.yaml") { Copy-Item "config.yaml" "dist\config.yaml" -Force }
Write-Host "Built dist\PokeRestock.exe" -ForegroundColor Green
