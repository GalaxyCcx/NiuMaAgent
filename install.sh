#!/bin/bash

# Chat2Excel - 依赖安装脚本 (Linux/macOS)

set -e

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       Chat2Excel - 依赖安装脚本 (Linux/macOS)          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ========================================
# 检查 Python
# ========================================
echo "[1/4] 检查 Python 环境..."

# 尝试找到 Python 3
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo ""
    echo "  [错误] 未检测到 Python！"
    echo ""
    echo "  请先安装 Python 3.10 或更高版本："
    echo "  - Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  - macOS: brew install python@3.11"
    echo "  - 或访问: https://www.python.org/downloads/"
    echo ""
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
echo "       √ Python $PYTHON_VERSION 已安装 ($PYTHON_CMD)"

# 检查版本
MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
    echo "  [警告] Python 版本较低 ($PYTHON_VERSION)，建议使用 3.10+"
fi

# 检查 venv 模块
if ! $PYTHON_CMD -m venv --help &> /dev/null; then
    echo ""
    echo "  [错误] Python venv 模块未安装"
    echo "  Ubuntu/Debian: sudo apt install python3-venv"
    echo ""
    exit 1
fi

# ========================================
# 创建虚拟环境
# ========================================
echo ""
echo "[2/4] 创建 Python 虚拟环境..."

cd backend

if [ -d "venv" ]; then
    echo "       √ 虚拟环境已存在"
else
    echo "       创建虚拟环境中..."
    $PYTHON_CMD -m venv venv
    echo "       √ 虚拟环境创建成功"
fi

# ========================================
# 激活虚拟环境并安装依赖
# ========================================
echo ""
echo "[3/4] 安装 Python 依赖包..."

source venv/bin/activate

echo "       升级 pip..."
pip install --upgrade pip -q

echo "       安装项目依赖..."
pip install -r requirements.txt

echo "       √ 所有依赖安装完成"

# ========================================
# 初始化配置
# ========================================
echo ""
echo "[4/4] 检查配置文件..."

cd ..

if [ -f "data/config.json" ]; then
    echo "       √ 配置文件已存在"
else
    echo "       创建默认配置文件..."
    mkdir -p data
    cat > data/config.json << 'EOF'
{
  "api_key": "your-api-key-here",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "default": {
    "model": "qwen3-max",
    "enable_thinking": true,
    "max_tokens": 8192,
    "temperature": 0.7,
    "top_p": 0.9
  },
  "agents": {}
}
EOF
    echo "       √ 配置文件已创建"
fi

# ========================================
# 完成
# ========================================
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                    安装完成！                            ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  下一步:                                                 ║"
echo "║  1. 编辑 data/config.json 填入你的 API Key              ║"
echo "║  2. 运行 ./start.sh 启动服务                            ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
