@echo off
chcp 65001 >nul
setlocal

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║            Chat2Excel - 数据分析 Agent                 ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ========================================
:: 检查环境
:: ========================================
echo [1/2] 检查环境...

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [错误] 未找到 Python！
    echo  请先运行 install.bat 安装依赖
    echo.
    pause
    exit /b 1
)

:: 检查虚拟环境
if not exist "backend\venv" (
    echo.
    echo  [错误] 虚拟环境不存在！
    echo  请先运行 install.bat 安装依赖
    echo.
    pause
    exit /b 1
)

:: 检查配置文件
if not exist "data\config.json" (
    echo.
    echo  [错误] 配置文件不存在！
    echo  请先运行 install.bat 安装依赖
    echo.
    pause
    exit /b 1
)

echo        √ 环境检查通过

:: ========================================
:: 启动服务
:: ========================================
echo.
echo [2/2] 启动后端服务...

cd backend
call venv\Scripts\activate.bat

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                     服务已启动                           ║
echo  ╠══════════════════════════════════════════════════════════╣
echo  ║                                                          ║
echo  ║  后端 API:    http://localhost:8000                      ║
echo  ║  API 文档:    http://localhost:8000/docs                 ║
echo  ║  前端界面:    用浏览器打开 frontend/index.html           ║
echo  ║  Agent 监控:  用浏览器打开 frontend/monitor.html         ║
echo  ║                                                          ║
echo  ╠══════════════════════════════════════════════════════════╣
echo  ║  按 Ctrl+C 停止服务                                      ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

python run.py
