@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\run-scheduled.ps1" -Profile oos
exit /b %errorlevel%
