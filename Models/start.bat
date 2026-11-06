@echo off
rem Starts Models on http://127.0.0.1:8800 and opens its page; the hub starts it with --no-browser.
cd /d "%~dp0"
python models.py %*
if errorlevel 1 pause
