#!/bin/bash
cd "$(dirname "$0")"

NO_PAUSE=false
[ "$1" = "--no-pause" ] && NO_PAUSE=true

# === 环境自愈：检测并创建虚拟环境 ===
if [ ! -d "venv" ]; then
    echo "[INFO] 检测到虚拟环境缺失，正在创建..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] 虚拟环境创建失败"
        exit 1
    fi
fi

# === 安装依赖 ===
echo "[INFO] 安装依赖..."
venv/bin/pip install -r requirements.txt --quiet

# === 后台启动 + PID ===
nohup venv/bin/python listener.py > /dev/null 2>&1 &
echo $! > .pid

if [ "$NO_PAUSE" = false ]; then
    echo "监听程序已在后台运行 (PID: $(cat .pid))"
    read -p "按回车键退出..."
fi
