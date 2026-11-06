@echo off
rem Starts Claudia Mini. AppHub passes --no-browser; she never opens a tab anyway.
rem Her page is http://127.0.0.1:8780/ and right-clicking her opens a menu.
start "" "%~dp0ClaudiaMini.exe"
