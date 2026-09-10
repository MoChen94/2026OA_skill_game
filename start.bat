@echo off
rem ============================================================
rem  OA协同办公平台 - 快速启动（Selector 事件循环，断网防崩）
rem  本机访问：http://127.0.0.1:8001
rem  局域网访问：http://本机IP:8001 （接口文档 /docs）
rem  停止服务：双击 stop.bat
rem ============================================================
title OA Launcher
cd /d %~dp0

rem 端口已监听 = 服务已在运行，直接打开浏览器
netstat -ano | findstr ":8001" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OA] 服务已在运行，正在打开浏览器...
    start http://127.0.0.1:8001
    goto :eof
)

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv，无法启动
    pause
    exit /b 1
)

echo [OA] 正在后台启动服务（最小化窗口）...
start "OA Server" /min cmd /c "cd /d %~dp0 && .venv\Scripts\python.exe backend\run.py 8001"

rem 等待端口就绪（最多 20 秒）
set /a n=0
:wait
ping -n 2 127.0.0.1 >nul
set /a n+=1
netstat -ano | findstr ":8001" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto ready
if %n% lss 20 goto wait

echo [错误] 服务 20 秒内未就绪，启动失败
pause
exit /b 1

:ready
echo [OA] 启动成功！正在打开浏览器...
start http://127.0.0.1:8001
echo 提示：任务栏最小化的 OA Server 窗口即服务，关闭它或运行 stop.bat 可停止服务
goto :eof
