@echo off
rem Starts Corpus on http://127.0.0.1:8760 and opens its page; the hub starts it with --no-browser.
cd /d "%~dp0"
python corpus.py %*
if errorlevel 1 pause
