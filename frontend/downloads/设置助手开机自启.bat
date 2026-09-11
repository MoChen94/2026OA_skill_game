@echo off
rem  桌面提醒助手开机自启（把本目录 exe 快捷方式放进启动文件夹，一次性设置）
rem  请确保 OATool-Notifier.exe（及 OA助手.ini）就在本目录
cd /d %~dp0
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $startup = [Environment]::GetFolderPath('Startup'); $s = $ws.CreateShortcut(\"$startup\" + 'OA提醒助手.lnk'); $s.TargetPath = '%~dp0OATool-Notifier.exe'; $s.WindowStyle = 7; $s.Save(); Write-Output ('lnk: ' + (Test-Path (\"$startup\" + 'OA提醒助手.lnk')))"
echo 设置完成（上方 lnk: True 即成功）
pause