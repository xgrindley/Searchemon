# Optional: start the monitor window when you sign in to Windows.
# Run again with -Remove to undo.
param([switch]$Remove)
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "Pokemon Restock Monitor.lnk"

if ($Remove) {
    Remove-Item $link -ErrorAction SilentlyContinue
    Write-Host "Removed from startup."
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$shortcut.Arguments = "app.py"
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Save()
Write-Host "Added to startup: $link" -ForegroundColor Green
