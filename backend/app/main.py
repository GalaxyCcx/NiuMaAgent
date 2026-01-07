"""
Chat2Excel 后端主应用
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .api.config_routes import router as config_router
from .api.chat_routes import router as chat_router
from .api.upload_routes import router as upload_router
from .api.report_routes import router as report_router
from .config import config_manager

# 创建应用
app = FastAPI(
    title="Chat2Excel API",
    description="数据分析 Agent 系统 API",
    version="0.1.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(config_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api", tags=["数据上传"])
app.include_router(report_router, prefix="/api")


# 静态文件（前端）- 直接服务开发目录
frontend_path = Path(__file__).parent.parent.parent / "frontend"
if frontend_path.exists():
    # 挂载静态文件
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(frontend_path / "index.html")
    
    @app.get("/report.html")
    async def serve_report():
        return FileResponse(frontend_path / "report.html")
    
    @app.get("/test-charts.html")
    async def serve_test_charts():
        return FileResponse(frontend_path / "test-charts.html")
    
    @app.get("/test-sort.html")
    async def serve_test_sort():
        return FileResponse(frontend_path / "test-sort.html")
    
    @app.get("/monitor.html")
    async def serve_monitor():
        return FileResponse(frontend_path / "monitor.html")
    
    @app.get("/{filename}.css")
    async def serve_css(filename: str):
        return FileResponse(frontend_path / f"{filename}.css", media_type="text/css")
    
    @app.get("/{filename}.js")
    async def serve_js(filename: str):
        return FileResponse(frontend_path / f"{filename}.js", media_type="application/javascript")


@app.get("/api/health", tags=["系统"])
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "configured": config_manager.is_configured(),
    }


@app.get("/api/status", tags=["系统"])
async def get_status():
    """获取系统状态"""
    return {
        "app_name": config_manager.app_settings.app_name,
        "version": "0.1.0",
        "api_configured": config_manager.is_configured(),
        "model": config_manager.llm_settings.default.model if config_manager.llm_settings else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

