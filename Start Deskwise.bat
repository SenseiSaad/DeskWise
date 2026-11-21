@echo off
setlocal
title Deskwise Local Launcher
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local.ps1" %*
if errorlevel 1 (
  echo.
  echo Deskwise launcher encountered an error. Review the messages above.
  pause
  exit /b 1
)
echo.
echo Press any key to close this launcher window (Deskwise stays running in Docker)...
pause >nul
