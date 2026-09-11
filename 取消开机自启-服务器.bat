@echo off
chcp 65001 >nul
set "STARTUPDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUPDIR%\OA-server.bat" (del "%STARTUPDIR%\OA-server.bat" & echo [OK] OA server auto-start removed) else (echo [SKIP] not enabled on this PC)
pause
