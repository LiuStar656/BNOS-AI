@echo off
setlocal

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo 错误：虚拟环境不存在，请先创建虚拟环境
    pause
    exit /b 1
)

echo 启动 listener.py...
echo 使用虚拟环境: venv\Scripts\python.exe
echo.

venv\Scripts\python.exe listener.py

endlocal
