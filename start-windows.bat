@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start-windows.ps1"
exit /b %errorlevel%
