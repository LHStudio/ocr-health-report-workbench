@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo Stopping OCR backend and frontend...

for %%S in (backend frontend) do (
  if exist ".run\%%S.pid" (
    set "SERVICE_PID="
    set /p SERVICE_PID=<".run\%%S.pid"
    if defined SERVICE_PID taskkill /PID !SERVICE_PID! /T /F >nul 2>nul
    del /q ".run\%%S.pid" >nul 2>nul
  )
)

rem Fallback for services started before PID tracking was added.
for /f "tokens=5" %%I in ('netstat -ano -p tcp ^| findstr /R /C:":8000 .*LISTENING" /C:":5173 .*LISTENING"') do taskkill /PID %%I /T /F >nul 2>nul

ping -n 2 127.0.0.1 >nul

netstat -ano -p tcp | findstr /R /C:":8000 .*LISTENING" /C:":5173 .*LISTENING" >nul
if not errorlevel 1 (
  echo Some services could not be stopped. Please close their command windows manually.
  pause
  exit /b 1
)

echo Backend and frontend have been stopped. Ports 8000 and 5173 are free.
ping -n 3 127.0.0.1 >nul
exit /b 0
