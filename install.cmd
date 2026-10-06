@echo off
setlocal DisableDelayedExpansion
title StarBridge Windows Setup
chcp 65001 >nul
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "STARBRIDGE_EXIT=%ERRORLEVEL%"
echo.
if not "%STARBRIDGE_EXIT%"=="0" echo Setup failed. Check the message above and retry.
pause
exit /b %STARBRIDGE_EXIT%
