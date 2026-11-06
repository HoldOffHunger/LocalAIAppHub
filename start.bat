@echo off
rem Starts every app (Local Chat, Images, Autonoma, AI Workers, Site Stats) and opens the App Hub at http://127.0.0.1:8700
rem Each app gets its own window, as before; closing this window stops only the hub page.
cd /d "%~dp0"
python hub_server.py
if errorlevel 1 pause
