@echo off
rem Starts Ollama if it isn't running, then the Warden, and opens it in your browser, signed in.
curl -s -m 3 http://127.0.0.1:11434/api/version >nul 2>&1
if errorlevel 1 (
  echo Ollama isn't running; starting it...
  start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
  for /l %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 >nul
    curl -s -m 2 http://127.0.0.1:11434/api/version >nul 2>&1 && goto ollama_up
  )
  echo Ollama didn't answer after 30 seconds; the Warden will start anyway.
)
:ollama_up
rem The hub starts it with --no-browser, since the hub already shows it
set OPEN_BROWSER=--open
if /i "%~1"=="--no-browser" set OPEN_BROWSER=
cd /d "%~dp0src"
"%~dp0.venv\Scripts\python.exe" run_warden.py %OPEN_BROWSER%
