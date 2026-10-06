@echo off
setlocal DisableDelayedExpansion
title StarBridge Stop
chcp 65001 >nul
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
set "STARBRIDGE_EXIT=%ERRORLEVEL%"
pause
exit /b %STARBRIDGE_EXIT%
