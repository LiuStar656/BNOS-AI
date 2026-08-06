#!/bin/bash
# BNOS Node Starter (Linux/macOS)

cd "$(dirname "$0")" || exit 1

export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

# 环境检测
if [ -f "venv/bin/python" ]; then
    PYTHON=venv/bin/python
elif [ -f "venv/bin/python3" ]; then
    PYTHON=venv/bin/python3
else
    echo "虚拟环境不存在，请先创建 venv"
    exit 1
fi

echo "启动监听程序..."
nohup "$PYTHON" listener.py > logs/stdout.log 2>&1 &
PID=$!
echo $PID > .pid
echo "监听程序已启动，PID: $PID"
