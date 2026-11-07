@echo off
rem Starts Local Chat and opens it in the browser. Requires Python 3 and Ollama running.
cd /d "%~dp0"
rem The App Hub starts it with --no-browser, since the hub already shows it
if /i not "%~1"=="--no-browser" start "" http://127.0.0.1:8790
python server.py
