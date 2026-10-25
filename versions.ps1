# Version snapshots, so a damaged install can go back to a release that worked.
#
#   .\versions.ps1 save "what changed"   take a snapshot of the program files
#   .\versions.ps1 list                  show snapshots (the stable one is marked)
#   .\versions.ps1 stable [name]         mark a snapshot as the known-good one (default: newest)
#   .\versions.ps1 restore [name]        go back to a snapshot (default: the stable one)
#
# Snapshots hold program files only. Your config.yaml, data folder (history,
# block stats, browser profiles) and the .venv are never touched.
param(
    [Parameter(Position = 0)][ValidateSet("save", "list", "stable", "restore")][string]$Action = "list",
    [Parameter(Position = 1)][string]$Arg = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dir = Join-Path $PSScriptRoot "versions"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$marker = Join-Path $dir "stable.txt"
$version = if (Test-Path "VERSION") { (Get-Content "VERSION" -Raw).Trim() } else { "unknown" }

# Program files only.
$items = @("app.py", "restock", "tests", "requirements.txt", "config.example.yaml", "README.md",
           "VERSION", "CHANGELOG.md", "NOTES.md", "RESOURCES.md",
           "setup.ps1", "run.ps1", "versions.ps1", "update.ps1", "RELEASING.md", "add-to-startup.ps1", "build-exe.ps1")

function Snapshot([string]$note, [string]$tag) {
    $stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
    $name = "v$version" + "_$stamp" + $(if ($tag) { "_$tag" } else { "" }) + ".zip"
    $path = Join-Path $dir $name
    $stage = Join-Path $env:TEMP ("poke-snap-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $stage | Out-Null
    foreach ($i in $items) {
        if (Test-Path $i) { Copy-Item $i -Destination $stage -Recurse -Force }
    }
    Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    if ($note) { Set-Content (Join-Path $stage "SNAPSHOT-NOTE.txt") $note }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $path -Force
    Remove-Item $stage -Recurse -Force
    return $name
}

function Resolve-Snap([string]$what) {
    if (-not $what -or $what -eq "stable") {
        if (Test-Path $marker) { $what = (Get-Content $marker -Raw).Trim() } else { return $null }
    }
    if ($what -eq "latest") {
        $f = Get-ChildItem $dir -Filter "*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($f) { return $f.Name } else { return $null }
    }
    if (-not $what.EndsWith(".zip")) { $what += "*.zip" }
    $f = Get-ChildItem $dir -Filter $what | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($f) { return $f.Name } else { return $null }
}

switch ($Action) {
    "save" {
        $n = Snapshot $Arg ""
        Write-Host "Saved snapshot $n" -ForegroundColor Green
        Write-Host "If this version works well, mark it:  .\versions.ps1 stable"
    }
    "list" {
        $stable = if (Test-Path $marker) { (Get-Content $marker -Raw).Trim() } else { "" }
        $zips = Get-ChildItem $dir -Filter "*.zip" | Sort-Object LastWriteTime -Descending
        if (-not $zips) { Write-Host "No snapshots yet. Make one with:  .\versions.ps1 save"; break }
        foreach ($z in $zips) {
            $mark = if ($z.Name -eq $stable) { "  <- stable" } else { "" }
            Write-Host ("{0}  {1:N0} KB{2}" -f $z.Name, ($z.Length / 1KB), $mark)
        }
        Write-Host "`nCurrent version: $version"
    }
    "stable" {
        $name = Resolve-Snap $(if ($Arg) { $Arg } else { "latest" })
        if (-not $name) { Write-Host "No snapshot found. Run .\versions.ps1 list" -ForegroundColor Red; exit 1 }
        Set-Content $marker $name
        Write-Host "Marked $name as the stable version." -ForegroundColor Green
    }
    "restore" {
        $name = Resolve-Snap $Arg
        if (-not $name) { Write-Host "No matching snapshot (or none marked stable). Run .\versions.ps1 list" -ForegroundColor Red; exit 1 }
        Write-Host "Closing the app if it is running..."
        Get-Process pythonw, python -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -like "$PSScriptRoot*" } | Stop-Process -Force -ErrorAction SilentlyContinue
        $safety = Snapshot "Automatic copy taken before restoring $name" "before-restore"
        Write-Host "Saved your current files as $safety (in case you want them back)."
        $stage = Join-Path $env:TEMP ("poke-restore-" + [guid]::NewGuid().ToString("N"))
        Expand-Archive -Path (Join-Path $dir $name) -DestinationPath $stage -Force
        foreach ($i in $items) {
            $src = Join-Path $stage $i
            if (-not (Test-Path $src)) { continue }
            if (Test-Path $i -PathType Container) { Remove-Item $i -Recurse -Force }
            Copy-Item $src -Destination . -Recurse -Force
        }
        Remove-Item $stage -Recurse -Force
        Write-Host "Restored $name. Your settings and data were not touched." -ForegroundColor Green
        Write-Host "Run  powershell -ExecutionPolicy Bypass -File .\setup.ps1  once, then  .\run.ps1"
    }
}
