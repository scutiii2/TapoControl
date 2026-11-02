# Build dist\TapoControl\ with PyInstaller, then dist\TapoControl-Setup.exe with Inno Setup if installed.
# Usage: build.ps1 [-SkipTests]
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot
Set-Location -LiteralPath $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"

# uv is a standalone tool; fall back to the pip-installed module. Without either, build from the existing .venv.
$pyUv = $false
try { & python -m uv --version *> $null; $pyUv = ($LASTEXITCODE -eq 0) } catch { }
if (Get-Command uv -ErrorAction SilentlyContinue) { & uv sync --frozen }
elseif ($pyUv) { & python -m uv sync --frozen }
elseif (Test-Path $Py) { Write-Host "uv not found; using the existing .venv as is (install: winget install astral-sh.uv)." -ForegroundColor Yellow; $global:LASTEXITCODE = 0 }
else { throw "uv not found and no .venv. Install uv: winget install astral-sh.uv, then run: uv sync" }
if ($LASTEXITCODE) { throw "uv sync failed" }
if (-not $SkipTests) { & $Py -m pytest -q; if ($LASTEXITCODE) { throw "tests failed" } }
# A running copy locks its files in dist and breaks the clean step.
Get-Process TapoControl -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
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
