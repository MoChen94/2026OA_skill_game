@echo off
chcp 65001 >nul
set "STARTUPDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LAUNCHER=%STARTUPDIR%\OA-notifier.bat"
> "%LAUNCHER%" echo @echo off
>>"%LAUNCHER%" echo start "" "%~dp0OATool-Notifier.exe"
if exist "%LAUNCHER%" (echo [OK] notifier auto-start enabled) else (echo [FAIL])
pause
