@echo off
chcp 65001 >nul
REM BNOS 一键启动 — 引擎由 GUI 客户端内部管理生命周期，此处仅启动 GUI
cd /d "%~dp0"

echo [BNOS] 启动 GUI 客户端（引擎由 GUI 自动管理）...
gui\venv\Scripts\python gui\main.py

echo [BNOS] GUI 已关闭，停止引擎...

REM 使用 process_killer 按 PID 文件清理所有节点进程（兜底）
gui\venv\Scripts\python -c "import sys; from pathlib import Path; sys.path.insert(0, '.'); from bnos_runtime.process_killer import stop_all_node_processes; stop_all_node_processes(Path('.').resolve()); print('[BNOS] 清理完成')" >nul 2>&1

echo [BNOS] 已退出
