@echo off
rem  设置 OA 服务器开机自动启动（把 start.bat 的快捷方式放进启动文件夹）
rem  断电来电后服务器重启，OA 服务将自动拉起，无需人工操作
chcp 65001 >nul
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut($env:STARTUP+'\OA服务.lnk'); $s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo [OK] 已设置开机自启：来电重启后 OA 服务自动启动
pause