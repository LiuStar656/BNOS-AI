@echo off
setlocal enabledelayedexpansion

if /i not "%1"=="--no-pause" (
    cls
    chcp 65001 >nul
    echo ======================================
    echo        BNOS Node Starter
    echo  LLM 推理节点 - node_python_llm_infer
    echo ======================================
    echo.
)

cd /d "%~dp0"

REM === 环境自愈：检测并创建虚拟环境 ===
if not exist "venv\Scripts\python.exe" (
    if /i not "%1"=="--no-pause" (
        echo [INFO] 检测到虚拟环境缺失，正在创建...
    )
    python -m venv venv
    if !errorlevel! neq 0 (
        echo [ERROR] 虚拟环境创建失败，请确保已安装 Python
        if /i not "%1"=="--no-pause" pause
        exit /b 1
    )
)

REM === 安装依赖 ===
if /i not "%1"=="--no-pause" (
    echo [INFO] 安装依赖...
)
venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if !errorlevel! neq 0 (
    echo [WARNING] 部分依赖安装失败，请检查 requirements.txt
)

REM === 后台启动 ===
if /i not "%1"=="--no-pause" (
    echo.
    echo 后台启动监听程序...
    start /b "" "venv\Scripts\python.exe" "listener.py"
) else (
    start /b "" "venv\Scripts\python.exe" "listener.py" >nul 2>&1
)

REM === 写入 PID ===
timeout /t 2 /nobreak >nul
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /nh 2^>nul') do echo %%i > .pid

if /i not "%1"=="--no-pause" (
    echo 监听程序已在后台运行 (PID: 请查看 .pid)
    echo.
    pause
)

endlocal
