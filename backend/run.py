"""
启动脚本
"""
import uvicorn
import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.platform == "win32":
    os.system("chcp 65001 > nul 2>&1")
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 设置日志目录
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志文件路径
log_file = LOG_DIR / f"server_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# 配置日志 - 同时输出到控制台和文件
class TeeOutput:
    """同时输出到控制台和文件"""
    def __init__(self, file_path, stream):
        self.file = open(file_path, 'a', encoding='utf-8')
        self.stream = stream
        self.encoding = 'utf-8'
    
    def write(self, data):
        self.stream.write(data)
        self.file.write(data)
        self.file.flush()
    
    def flush(self):
        self.stream.flush()
        self.file.flush()
    
    def isatty(self):
        return False
    
    def fileno(self):
        return self.stream.fileno()

# 重定向输出
sys.stdout = TeeOutput(log_file, sys.stdout)
sys.stderr = TeeOutput(log_file, sys.stderr)

if __name__ == "__main__":
    # 通过命令行参数控制是否启用热重载
    reload_mode = "--reload" in sys.argv or "-r" in sys.argv
    
    print("=" * 60)
    print("Chat2Excel 后端服务启动中...")
    print(f"日志文件: {log_file}")
    print("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload_mode,
    )

