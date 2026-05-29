@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\run-scheduled.ps1" -Profile weekly -IncludeReview -IncludeAlerts -AlertMax 10
exit /b %errorlevel%
