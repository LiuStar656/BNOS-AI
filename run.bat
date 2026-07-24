@echo off
chcp 65001 >nul
REM BNOS 一键启动 — 后台启动引擎（所有Python节点）+ Live2D + 前台 GUI 客户端
cd /d "%~dp0"

echo [BNOS] 启动引擎（所有节点）...
REM 后台启动引擎，不弹新窗口，日志写入 engine.log
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /B "" python -m bnos_runtime.engine pipeline.json > engine.log 2>&1

echo [BNOS] 等待节点初始化...
timeout /t 3 /nobreak >nul

echo [BNOS] 启动 GUI 客户端...
REM GUI 在前台运行，当前窗口即为 GUI 窗口
gui\venv\Scripts\python gui\main.py

echo [BNOS] GUI 已关闭，停止引擎...

REM 用 PowerShell 杀掉所有引擎 + listener 进程（比 wmic 更可靠，支持 Python 3.14+）
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*python*' -and ( $_.CommandLine -match 'bnos_runtime.engine' -or ( $_.CommandLine -match 'listener' -and $_.CommandLine -match 'node_' ) ) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [BNOS] 已退出
