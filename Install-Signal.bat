@echo off
title Install Signal
echo.
echo Installing Signal. This downloads the project (about a minute) and puts a Signal icon on your desktop.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $d=Join-Path $env:USERPROFILE 'Signal'; New-Item -ItemType Directory -Force $d | Out-Null; $z=Join-Path $env:TEMP 'signal.zip'; Write-Host 'Downloading...'; Invoke-WebRequest -UseBasicParsing 'https://github.com/SushiWarriorX/atlastradingterminal/archive/refs/heads/feature/research-modules.zip' -OutFile $z; Write-Host 'Unpacking...'; Expand-Archive -Force $z $d; $r=(Get-ChildItem $d -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName; & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $r 'create-signal-shortcut.ps1')"
if errorlevel 1 (
  echo.
  echo Something went wrong. Take a screenshot of this window and send it.
  pause
  exit /b 1
)
echo.
echo Done. Look for the Signal icon on your desktop.
pause
