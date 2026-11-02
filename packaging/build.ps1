# Build dist\TapoControl\ with PyInstaller, then dist\TapoControl-Setup.exe with Inno Setup if installed.
# Usage: build.ps1 [-SkipTests]
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot
Set-Location -LiteralPath $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) { & python -m venv .venv; if ($LASTEXITCODE) { throw "venv failed" } }
& $Py -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE) { throw "pip install failed" }
if (-not $SkipTests) { & $Py -m pytest -q; if ($LASTEXITCODE) { throw "tests failed" } }
& $Py -m PyInstaller packaging/build.spec --noconfirm
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
    & $iscc packaging/installer.iss
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    Write-Host "Done: dist\TapoControl-Setup.exe" -ForegroundColor Green
} else {
    Write-Host "Built dist\TapoControl\ only. Install Inno Setup (winget install JRSoftware.InnoSetup) and re-run for the installer." -ForegroundColor Yellow
}
