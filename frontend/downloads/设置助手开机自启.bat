@echo off
rem  设置桌面提醒助手开机自动启动（把本目录 exe 的快捷方式放进启动文件夹）
rem  断电来电后助手自动运行，配合已记住的配置免输入直接监听
chcp 65001 >nul
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut($env:STARTUP+'\OA提醒助手.lnk'); $s.TargetPath='%~dp0OATool-Notifier.exe'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo [OK] 已设置开机自启：来电重启后提醒助手自动运行
echo 提示：请先把 OATool-Notifier.exe 和 OA助手.ini 放在本目录再运行本脚本
pause