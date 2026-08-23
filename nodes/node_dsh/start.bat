@echo off
REM BNOS 节点启动：node_dsh（DeepSeek Harness 执行器官）
chcp 65001 >nul
cd /d "%~dp0"

REM 优先源码版（harness/ 源码仓库 + pnpm 安装）
if exist "harness\apps\cli\src\bin.ts" (
    if not exist "harness\node_modules\tsx" (
        echo [node_dsh] 源码版未安装依赖，正在执行 pnpm install...
        pushd harness
        call pnpm install --ignore-scripts
        call pnpm run build:lib:host
        popd
    )
    echo [node_dsh] 使用源码版 DSH（harness/，改源码即改即用）
    goto start
)

REM fallback：npm 编译包
if not exist "node_modules\@deepseek-ai\dsh\lib\bin.js" (
    echo [node_dsh] 未检测到 DSH 编译包，正在安装 @deepseek-ai/dsh...
    call npm install --no-audit --no-fund
)

:start
echo [node_dsh] 启动 listener.py ...
python listener.py
