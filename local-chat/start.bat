@echo off
rem Starts Local Chat and opens it in the browser. Requires Python 3 and Ollama running.
cd /d "%~dp0"
start "" http://127.0.0.1:8790/hub
python server.py
