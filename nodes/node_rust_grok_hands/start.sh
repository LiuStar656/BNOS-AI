#!/bin/bash

cd "$(dirname "$0")"

echo "======================================"
echo "        BNOS Rust Node Starter"
echo "======================================"
echo ""

# ==================== 环境检测与自愈 ====================
echo "🔍 检测 Rust 环境和编译产物..."

NEED_BUILD=0

if [ ! -f "target/release/node_rust_grok_hands" ]; then
    echo "⚠️ 检测到 node_rust_grok_hands 缺失"
    NEED_BUILD=1
fi

if [ ! -f "target/release/node_rust_grok_hands_listener" ]; then
    echo "⚠️ 检测到 node_rust_grok_hands_listener 缺失"
    NEED_BUILD=1
fi

if [ "$NEED_BUILD" -eq 1 ]; then
    echo ""
    echo "🔧 开始自动构建..."
    echo ""

    # 检查 Rust 是否安装
    if ! command -v rustc &> /dev/null; then
        echo "❌ Rust 未安装"
        echo "💡 请先安装 Rust: https://rustup.rs/"
        if [ "$1" != "--no-pause" ]; then
            read -p "按回车键退出..."
        fi
        exit 1
    fi

    # 构建项目
    cargo build --release
    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ 构建失败"
        if [ "$1" != "--no-pause" ]; then
            read -p "按回车键退出..."
        fi
        exit 1
    fi
    echo ""
    echo "✅ 构建成功"
else
    echo "✅ 编译产物检测通过"
fi

echo ""
echo "✅ 后台启动监听程序..."
echo ""
nohup ./target/release/node_rust_grok_hands_listener > /dev/null 2>&1 &
echo $! > .pid
echo "✅ 监听程序已在后台运行 (PID: $(cat .pid))"
if [ "$1" != "--no-pause" ]; then
    read -p "按回车键退出..."
fi
