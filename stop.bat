@echo off
rem ============================================================
rem  OA 工业运维管理平台 - 快速关闭
rem  停止 8001 端口上的服务进程（会处理所有重复实例）
rem ============================================================
title OA Stopper
cd /d %~dp0

set WASRUN=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
    set WASRUN=1
)

if "%WASRUN%"=="0" (
    echo [OA] 未检测到运行中的服务（端口 8001 空闲）
) else (
    echo [OA] 服务进程已全部停止
)
goto :eof
