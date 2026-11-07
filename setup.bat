@echo off
rem Shows what setup would download for this PC, then asks before doing it.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File setup\setup.ps1 -DryRun
echo.
choice /m "Go ahead and download these"
if errorlevel 2 goto :eof
powershell -NoProfile -ExecutionPolicy Bypass -File setup\setup.ps1
pause
