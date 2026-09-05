@echo off
REM Windows launcher — double-click or run from cmd/PowerShell.
REM Passes all args through to run.ps1 / simulatecraft (same as ./run.sh).
setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo Missing PowerShell. Install Windows PowerShell or PowerShell 7.
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %ERRORLEVEL%
