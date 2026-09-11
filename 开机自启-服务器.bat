@echo off
rem  OA 服务器开机自启（把 start.bat 快捷方式放进启动文件夹，一次性设置）
rem  断电来电后服务器重启，OA 服务自动拉起，无需人工操作
cd /d %~dp0
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $startup = [Environment]::GetFolderPath('Startup'); $s = $ws.CreateShortcut(\"$startup\" + 'OA服务.lnk'); $s.TargetPath = '%~dp0start.bat'; $s.WindowStyle = 7; $s.Save(); Write-Output ('lnk: ' + (Test-Path (\"$startup\" + 'OA服务.lnk')))"
echo 设置完成（上方 lnk: True 即成功）
pause