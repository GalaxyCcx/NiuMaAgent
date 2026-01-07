# Chat2Excel

智能数据分析 Agent 系统 - 上传数据，对话生成专业分析报告

## 功能特性

- **自主上传数据** - 支持 CSV 文件上传，自动解析数据结构
- **智能知识库** - 自动构建数据知识库，理解数据语义
- **多轮对话** - 通过自然语言对话进行数据分析
- **专业报告** - 多 Agent 协作生成专业数据分析报告
- **可视化图表** - 自动生成 ECharts 数据可视化
- **实时监控** - Agent Monitor 实时查看 Agent 运行状态

## 环境要求

- Python 3.10+
- 阿里云百炼 API Key (或其他兼容 OpenAI API 的服务)

## 快速开始

### Windows

```bash
# 1. 克隆项目
git clone https://github.com/your-username/Chat2Excel.git
cd Chat2Excel

# 2. 安装依赖
install.bat

# 3. 编辑 data/config.json 填入 API Key

# 4. 启动服务
start.bat
```

### Linux / macOS

```bash
# 1. 克隆项目
git clone https://github.com/your-username/Chat2Excel.git
cd Chat2Excel

# 2. 添加执行权限
chmod +x install.sh start.sh

# 3. 安装依赖
./install.sh

# 4. 编辑 data/config.json 填入 API Key

# 5. 启动服务
./start.sh
```

## 访问地址

| 地址 | 说明 |
|------|------|
| http://localhost:8000 | 后端 API |
| http://localhost:8000/docs | API 文档 |
| frontend/index.html | 主界面 |
| frontend/report.html | 报告页面 |
| frontend/monitor.html | Agent 监控 |

## 项目结构

```
Chat2Excel/
├── backend/           # 后端服务
│   ├── app/          # 应用代码
│   ├── requirements.txt
│   └── run.py
├── frontend/          # 前端界面
│   ├── index.html
│   ├── report.html
│   └── monitor.html
├── data/              # 数据目录
│   └── config.json   # 配置文件
├── prompt/            # Prompt 模板
├── tools/             # Tool 定义
├── install.bat/sh     # 安装脚本
├── start.bat/sh       # 启动脚本
└── README.md
```

## 配置说明

编辑 `data/config.json` 配置 API：

```json
{
  "api_key": "your-api-key-here",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "default": {
    "model": "qwen3-max",
    "enable_thinking": true,
    "max_tokens": 8192,
    "temperature": 0.7
  }
}
```

## 使用流程

1. 上传数据 - 在主界面上传 CSV 文件
2. 配置 API - 在设置中填入 API Key
3. 开始对话 - 用自然语言描述分析需求
4. 查看报告 - 系统自动生成分析报告
5. 监控进度 - Monitor 页面查看 Agent 状态

## API 接口

- `GET /api/config` - 获取配置
- `PUT /api/config` - 更新配置
- `POST /api/data/upload` - 上传文件
- `POST /api/chat` - 对话 (SSE)
- `GET /api/chat/monitor/{session_id}` - 监控
- `GET /api/report/{session_id}` - 获取报告
- `GET /api/health` - 健康检查

## License

MIT
