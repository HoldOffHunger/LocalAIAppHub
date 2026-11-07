@echo off
rem Starts ImageGen and opens it in the browser. ComfyUI wakes up on its own, headless, in the background.
cd /d "%~dp0"
rem The App Hub starts it with --no-browser, since the hub already shows it
if /i not "%~1"=="--no-browser" start "" http://127.0.0.1:8730
python server.py
if errorlevel 1 pause
