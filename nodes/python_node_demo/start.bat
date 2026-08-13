@echo off
setlocal enabledelayedexpansion
if not "%1"=="--no-pause" (
    cls
    chcp 65001 >nul
    echo ======================================
    echo        BNOS Node Starter
    echo ======================================
    echo.
)
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

REM === 环境自愈（按需实现） ===
if exist "venv\Scripts\python.exe" (
    echo 虚拟环境正常
) else (
    echo 虚拟环境不存在，请先运行 setup 脚本创建 venv
    if not "%1"=="--no-pause" pause
    exit /b 1
)

REM === 后台启动 ===
echo 后台启动监听程序...
if not "%1"=="--no-pause" (
    start /b "" venv\Scripts\python.exe listener.py
) else (
    start /b "" venv\Scripts\python.exe listener.py >nul 2>&1
)

REM === 写入 PID ===
timeout /t 1 /nobreak >nul
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /nh 2^>nul') do (
    echo %%i > .pid
    goto :found
)
echo 0 > .pid
:found

if not "%1"=="--no-pause" (
    echo 监听程序已在后台运行
    pause
)
endlocal
