@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║         Chat2Excel - 依赖安装脚本 (Windows)            ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ========================================
:: 检查 Python
:: ========================================
echo [1/4] 检查 Python 环境...

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [错误] 未检测到 Python！
    echo.
    echo  请先安装 Python 3.10 或更高版本：
    echo  下载地址: https://www.python.org/downloads/
    echo.
    echo  安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo        √ Python %PYTHON_VERSION% 已安装

:: 检查 Python 版本是否 >= 3.10
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)
if %MAJOR% LSS 3 (
    echo  [错误] Python 版本过低，需要 3.10+
    pause
    exit /b 1
)
if %MAJOR% EQU 3 if %MINOR% LSS 10 (
    echo  [警告] Python 版本较低 (%PYTHON_VERSION%)，建议使用 3.10+
)

:: ========================================
:: 创建虚拟环境
:: ========================================
echo.
echo [2/4] 创建 Python 虚拟环境...

cd backend

if exist "venv" (
    echo        √ 虚拟环境已存在
) else (
    echo        创建虚拟环境中...
    python -m venv venv
    if errorlevel 1 (
        echo  [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo        √ 虚拟环境创建成功
)

:: ========================================
:: 激活虚拟环境并安装依赖
:: ========================================
echo.
echo [3/4] 安装 Python 依赖包...

call venv\Scripts\activate.bat

echo        升级 pip...
python -m pip install --upgrade pip -q

echo        安装项目依赖...
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo  [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)

echo        √ 所有依赖安装完成

:: ========================================
:: 初始化配置
:: ========================================
echo.
echo [4/4] 检查配置文件...

cd ..

if exist "data\config.json" (
    echo        √ 配置文件已存在
) else (
    echo        创建默认配置文件...
    if not exist "data" mkdir data
    (
        echo {
        echo   "api_key": "your-api-key-here",
        echo   "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        echo   "default": {
        echo     "model": "qwen3-max",
        echo     "enable_thinking": true,
        echo     "max_tokens": 8192,
        echo     "temperature": 0.7,
        echo     "top_p": 0.9
        echo   },
        echo   "agents": {}
        echo }
    ) > data\config.json
    echo        √ 配置文件已创建
)

:: ========================================
:: 完成
:: ========================================
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                    安装完成！                            ║
echo  ╠══════════════════════════════════════════════════════════╣
echo  ║                                                          ║
echo  ║  下一步:                                                 ║
echo  ║  1. 编辑 data\config.json 填入你的 API Key              ║
echo  ║  2. 运行 start.bat 启动服务                             ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

pause
