@echo off
rem Starts Voice and opens it in the browser. Needs Ollama running, and this folder's .venv (see README.md).
cd /d "%~dp0"
rem The App Hub starts it with --no-browser, since the hub already shows it
if /i not "%~1"=="--no-browser" start "" http://127.0.0.1:8795
".venv\Scripts\python.exe" server.py
