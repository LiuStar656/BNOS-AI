#!/usr/bin/env bash
# BNOS Pipeline Runner — 自动生成的启动脚本
# 使用: bash run.sh
set -e
cd "$(dirname "$0")"
python -m bnos_runtime.engine pipeline.json
