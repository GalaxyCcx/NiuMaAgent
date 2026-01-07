#!/bin/bash

# Chat2Excel - 一键启动脚本 (Linux/macOS)

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║            Chat2Excel - 数据分析 Agent                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ========================================
# 检查环境
# ========================================
echo "[1/2] 检查环境..."

# 检查虚拟环境
if [ ! -d "backend/venv" ]; then
    echo ""
    echo "  [错误] 虚拟环境不存在！"
    echo "  请先运行 ./install.sh 安装依赖"
    echo ""
    exit 1
fi

# 检查配置文件
if [ ! -f "data/config.json" ]; then
    echo ""
    echo "  [错误] 配置文件不存在！"
    echo "  请先运行 ./install.sh 安装依赖"
    echo ""
    exit 1
fi

echo "       √ 环境检查通过"

# ========================================
# 启动服务
# ========================================
echo ""
echo "[2/2] 启动后端服务..."

cd backend
source venv/bin/activate

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                     服务已启动                           ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  后端 API:    http://localhost:8000                      ║"
echo "║  API 文档:    http://localhost:8000/docs                 ║"
echo "║  前端界面:    用浏览器打开 frontend/index.html           ║"
echo "║  Agent 监控:  用浏览器打开 frontend/monitor.html         ║"
echo "║                                                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  按 Ctrl+C 停止服务                                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

python run.py
