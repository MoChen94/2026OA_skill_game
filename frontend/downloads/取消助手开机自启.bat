@echo off
chcp 65001 >nul
set "STARTUPDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUPDIR%\OA-notifier.bat" (del "%STARTUPDIR%\OA-notifier.bat" & echo [OK] notifier auto-start removed) else (echo [SKIP] not enabled on this PC)
pause
