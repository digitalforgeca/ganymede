<#
.SYNOPSIS
Installs the Ganymede gateway on Windows.
#>

Write-Host "Starting Ganymede installation for Windows..." -ForegroundColor Cyan

$InstallDir = "$env:LOCALAPPDATA\Ganymede"
$VenvDir = "$InstallDir\venv"

if (-Not (Test-Path -Path $InstallDir)) {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
}

Write-Host "Creating Python virtual environment in $VenvDir..."
python -m venv $VenvDir

Write-Host "Upgrading pip and packaging tools..."
& "$VenvDir\Scripts\python.exe" -m pip install -q -U pip setuptools wheel

Write-Host "Installing Ganymede..."
# Assumes this script is run from the project root
& "$VenvDir\Scripts\pip.exe" install .

Write-Host "Creating Desktop Shortcut Launcher..."
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutScript = "$DesktopPath\Start-Ganymede.bat"

$BatContent = @"
@echo off
echo Starting Ganymede Gateway...
set GANYMEDE_DATA_DIR=%USERPROFILE%\.ganymede\data
"%VenvDir%\Scripts\ganymede.exe" run
pause
"@

Set-Content -Path $ShortcutScript -Value $BatContent

Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "You can start Ganymede by double-clicking 'Start-Ganymede.bat' on your desktop."
Write-Host "The dashboard will be available at http://localhost:8080"
