@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1" -SignalOnly %*
if errorlevel 1 pause
