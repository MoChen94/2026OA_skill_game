@echo off
chcp 65001 >nul
set "STARTUPDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LAUNCHER=%STARTUPDIR%\OA-server.bat"
> "%LAUNCHER%" echo @echo off
>>"%LAUNCHER%" echo cd /d "%~dp0."
>>"%LAUNCHER%" echo call "%~dp0start.bat"
if exist "%LAUNCHER%" (echo [OK] OA server auto-start enabled) else (echo [FAIL])
pause
