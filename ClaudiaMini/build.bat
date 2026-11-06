@echo off
rem Builds ClaudiaMini.exe and claudia-signal.exe with Visual Studio 2022's compiler,
rem then copies claudia-signal.exe into the plugin so its hooks can run it.
setlocal
cd /d "%~dp0"
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
if not exist build mkdir build

cl /nologo /O2 /EHsc /std:c++17 /W3 /DUNICODE /D_UNICODE /Fobuild\ src\overlay.cpp /Fe:ClaudiaMini.exe ^
   /link /SUBSYSTEM:WINDOWS user32.lib gdi32.lib ole32.lib windowscodecs.lib ws2_32.lib winmm.lib shell32.lib winhttp.lib || exit /b 1

cl /nologo /O2 /EHsc /std:c++17 /W3 /Fobuild\ src\signal.cpp /Fe:build\claudia-signal.exe ^
   /link /SUBSYSTEM:CONSOLE ws2_32.lib || exit /b 1

copy /y build\claudia-signal.exe marketplace\plugins\claudia-mini\bin\claudia-signal.exe >nul || exit /b 1
echo Built ClaudiaMini.exe and the plugin's claudia-signal.exe
