@echo off
rem OATool 工单桌面提醒助手 - 一键启动
rem 首次运行按提示输入服务器地址、账号、密码；窗口可最小化
cd /d %~dp0
python "%~dp0工单提醒助手.py"
pause
