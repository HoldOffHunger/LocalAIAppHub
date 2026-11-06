@echo off
rem Starts Chron Jobs on http://127.0.0.1:8740 and opens its page; the hub starts it with --no-browser.
cd /d "%~dp0"
python chron_jobs.py %*
if errorlevel 1 pause
