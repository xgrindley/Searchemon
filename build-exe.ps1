# Builds a single PokeRestock.exe in .\dist, checks it, and zips it.
#   .\build-exe.ps1
# Keep config.yaml in the same folder as the .exe (it is created from config.example.yaml on first run).
# Put an icon at assets\icon.ico if you want one; the build uses it when it exists.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run setup.ps1 first (there is no .venv yet)." }

$version = (Get-Content VERSION -ErrorAction Stop | Select-Object -First 1).Trim()
Write-Host "Building Searchemon v$version" -ForegroundColor Cyan

& $py -m pip install pyinstaller --quiet
& $py -m pip install -r requirements.txt --quiet

# The exe's Properties > Details tab (name, version, description).
$parts = ($version -split "\.") + @("0", "0", "0")
$tuple = "$($parts[0]), $($parts[1]), 0, 0"
New-Item -ItemType Directory -Force build | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($tuple), prodvers=($tuple), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Searchemon'),
      StringStruct('FileDescription', 'Pokemon TCG restock monitor'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'PokeRestock'),
      StringStruct('OriginalFilename', 'PokeRestock.exe'),
      StringStruct('ProductName', 'Searchemon'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content build\version-info.txt -Encoding UTF8

$pyArgs = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "PokeRestock",
    "--version-file", "build\version-info.txt",
    # Bundled files (VERSION and the example settings are read at run time).
    "--add-data", "VERSION;.", "--add-data", "config.example.yaml;.", "--add-data", "restock\fonts;restock\fonts",
    # Libraries PyInstaller cannot see by itself, or that ship data files.
    "--collect-submodules", "winotify",
    "--collect-all", "playwright",
    "--collect-all", "patchright",
    "--collect-all", "curl_cffi",
    "--collect-all", "zipcodes",
    "--collect-data", "certifi",
    "--hidden-import", "h2", "--hidden-import", "hpack", "--hidden-import", "hyperframe",
    "--hidden-import", "yaml", "--hidden-import", "tkinter",
    "--collect-submodules", "restock",
    "app.py"
)
if (Test-Path "assets\icon.ico") { $pyArgs += @("--icon", "assets\icon.ico") }
& $py -m PyInstaller @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Copy-Item "config.example.yaml" "dist\config.example.yaml" -Force
Copy-Item "VERSION" "dist\VERSION" -Force
if (Test-Path "config.yaml") { Copy-Item "config.yaml" "dist\config.yaml" -Force }

# Check the fresh build: it must start, find its bundled files and import everything it needs.
$report = "dist\selftest.txt"
Remove-Item $report -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "dist\PokeRestock.exe" -ArgumentList "--selftest" -Wait -PassThru -WindowStyle Hidden
if (Test-Path $report) { Get-Content $report | Write-Host }
if ($p.ExitCode -ne 0) { throw "The built exe failed its self-test (see above). Not zipped." }
Remove-Item $report -ErrorAction SilentlyContinue

# Zip it (without your config.yaml, so you can share it) and print a checksum.
$zip = "dist\PokeRestock-v$version.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\PokeRestock.exe", "dist\config.example.yaml", "dist\VERSION" -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
Write-Host ""
Write-Host "Built dist\PokeRestock.exe  ($([math]::Round((Get-Item dist\PokeRestock.exe).Length / 1MB, 1)) MB)" -ForegroundColor Green
Write-Host "Zip:    $zip"
Write-Host "SHA256: $hash"
Write-Host "Self-test passed. Browser checking uses the Microsoft Edge already on this PC."
