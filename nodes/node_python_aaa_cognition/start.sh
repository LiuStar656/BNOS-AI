#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f "venv/bin/python" ]; then
    echo "错误：虚拟环境不存在，请先创建虚拟环境"
    exit 1
fi

echo "启动 listener.py..."
echo "使用虚拟环境: venv/bin/python"
echo ""

venv/bin/python listener.py
