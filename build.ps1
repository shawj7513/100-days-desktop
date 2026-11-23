# Builds dist\100DaysTracker\ (the app) and, if Inno Setup is installed,
# dist\installer\100DaysTracker-Setup.exe (the installer to send to her).
#
#   powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

uv run pyinstaller --noconfirm --clean --windowed --name 100DaysTracker `
    --paths src --add-data "public;public" `
    --collect-data tzdata --collect-submodules uvicorn --collect-submodules webview `
    src/app.py

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc installer.iss
    Write-Host "Installer: dist\installer\100DaysTracker-Setup.exe"
} else {
    Write-Host "Inno Setup not found, so no installer was made."
    Write-Host "The app itself is in dist\100DaysTracker\ (run 100DaysTracker.exe)."
    Write-Host "Get Inno Setup (free) from https://jrsoftware.org/isinfo.php, then run this again."
}
