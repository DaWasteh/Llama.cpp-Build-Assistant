@echo off
setlocal
REM The helper bootstraps Python and launches the GUI independently of CMD.
start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\launch_windows.ps1"
exit /b
