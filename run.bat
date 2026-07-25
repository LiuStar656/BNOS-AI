@echo off
chcp 65001 >nul
REM BNOS 一键启动 — 引擎由 GUI 客户端内部管理生命周期，此处仅启动 GUI
cd /d "%~dp0"

echo [BNOS] 启动 GUI 客户端（引擎由 GUI 自动管理）...
gui\venv\Scripts\python gui\main.py

echo [BNOS] GUI 已关闭，停止引擎...

REM 用 PowerShell 杀掉所有引擎 + listener 进程树
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*python*' -and ( $_.CommandLine -match 'bnos_runtime.engine' -or ( $_.CommandLine -match 'listener' -and $_.CommandLine -match 'node_' ) ) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

REM 再兜底一次：直接杀死残留的 python listener 进程
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*python*' -and $_.CommandLine -match 'listener' -and $_.CommandLine -match 'node_' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [BNOS] 已退出
