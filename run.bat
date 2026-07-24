@echo off
chcp 65001 >nul
REM BNOS 一键启动 — 后台启动引擎（所有Python节点）+ 前台 GUI 客户端
cd /d "%~dp0"

echo [BNOS] 启动引擎（所有节点）...
REM 后台启动引擎，不弹新窗口，日志写入 engine.log
REM 使用 -m 方式确保引擎内部 from bnos_runtime.xxx 导入正常
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
start /B "" python -m bnos_runtime.engine pipeline.json > engine.log 2>&1

echo [BNOS] 等待节点初始化...
timeout /t 3 /nobreak >nul

echo [BNOS] 启动 GUI 客户端...
gui\venv\Scripts\python gui\main.py

echo [BNOS] GUI 已关闭，停止引擎...

REM 用 PowerShell 杀掉所有引擎 + listener 进程树
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*python*' -and ( $_.CommandLine -match 'bnos_runtime.engine' -or ( $_.CommandLine -match 'listener' -and $_.CommandLine -match 'node_' ) ) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

REM 再兜底一次：直接杀死残留的 python listener 进程
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*python*' -and $_.CommandLine -match 'listener' -and $_.CommandLine -match 'node_' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [BNOS] 已退出
