@echo off
rem ============================================================
rem  OA 工业运维管理平台 - 一键安装环境
rem  新电脑部署只需：装好 Python 3.11（64位）→ 双击本脚本 → start.bat
rem  优先使用本地 wheels 离线安装，没有 wheels 才走网络
rem ============================================================
title OA Setup
cd /d %~dp0

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python。
    echo        请先到 python.org 下载 Python 3.11 64位安装，
    echo        安装时务必勾选 "Add python.exe to PATH"！
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYV=%%v
echo [OA] 检测到 Python %PYV%

if not exist ".venv\Scripts\python.exe" (
    echo [OA] 正在创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
) else (
    echo [OA] 虚拟环境已存在，跳过创建
)

echo [OA] 正在安装依赖...
if exist "wheels" (
    echo [OA] 使用本地离线包 wheels\ 安装（无需联网）...
    .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements.txt -r requirements-dev.txt
) else (
    echo [OA] 未找到 wheels 目录，走网络安装（清华镜像）...
    .venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络或 wheels 目录
    pause
    exit /b 1
)

echo [OA] 环境安装完成！双击 start.bat 即可启动系统。
pause
