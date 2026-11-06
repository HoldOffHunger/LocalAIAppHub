@echo off
rem GGCMS Stats on http://127.0.0.1:8770 -- loopback only, never the network.
cd /d "%~dp0"
rem The hub starts it with --no-browser, since the hub already shows it
if /i not "%~1"=="--no-browser" start "" http://127.0.0.1:8770/
php -d memory_limit=512M -S 127.0.0.1:8770 -t public
