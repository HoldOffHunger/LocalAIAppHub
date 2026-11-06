@echo off
rem Starts Social on http://127.0.0.1:8750 and opens its page; the hub starts it with --no-browser.
cd /d "%~dp0"
python social.py %*
if errorlevel 1 pause
