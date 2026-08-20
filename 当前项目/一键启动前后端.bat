@echo off
setlocal
cd /d "%~dp0"

where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm was not found. Please install Node.js first.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python first.
  pause
  exit /b 1
)

if not exist "node_modules\.bin\vite.cmd" (
  echo Installing frontend dependencies for the first run...
  call npm install
  if errorlevel 1 (
    echo npm install failed.
    pause
    exit /b 1
  )
)

if not exist ".run" mkdir ".run"

echo Checking backend...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/medical-template-status' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo Starting backend...
  powershell -NoProfile -Command "$p = Start-Process -FilePath $env:ComSpec -ArgumentList '/k', 'call npm run backend' -WorkingDirectory '%~dp0' -PassThru; Set-Content -LiteralPath '.run\backend.pid' -Value $p.Id"
  call :wait_for_url "http://127.0.0.1:8000/medical-template-status" 60
  if errorlevel 1 (
    echo Backend did not become ready within 60 seconds.
    echo Check the OCR Backend window for details.
    pause
    exit /b 1
  )
) else (
  echo Backend is already running.
)

echo Checking frontend...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
  echo Starting frontend...
  powershell -NoProfile -Command "$p = Start-Process -FilePath $env:ComSpec -ArgumentList '/k', 'call npm run dev' -WorkingDirectory '%~dp0' -PassThru; Set-Content -LiteralPath '.run\frontend.pid' -Value $p.Id"
  call :wait_for_url "http://127.0.0.1:5173" 30
  if errorlevel 1 (
    echo Frontend did not become ready within 30 seconds.
    echo Check the OCR Frontend window for details.
    pause
    exit /b 1
  )
) else (
  echo Frontend is already running.
)

if /i "%~1"=="--no-browser" exit /b 0

echo Opening http://127.0.0.1:5173
start "" "http://127.0.0.1:5173"
exit /b 0

:wait_for_url
set "WAIT_URL=%~1"
set /a "WAIT_LIMIT=%~2"
set /a WAIT_COUNT=0

:wait_loop
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%WAIT_URL%' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 exit /b 0
set /a WAIT_COUNT+=1
if %WAIT_COUNT% geq %WAIT_LIMIT% exit /b 1
timeout /t 1 /nobreak >nul
goto wait_loop
