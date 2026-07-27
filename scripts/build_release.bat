@echo off
setlocal
set "ROOT=%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1" %*
exit /b %ERRORLEVEL%
