@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0scripts\bootstrap_and_run.ps1" %*

if errorlevel 1 (
    echo.
    echo Startup failed. Review the message above, then press any key to close.
    pause >nul
)

endlocal
