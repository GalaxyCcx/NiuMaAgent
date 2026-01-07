"""
配置管理 API 路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from ..config import config_manager, LLMSettings, DefaultLLMConfig, AgentConfig
from ..llm import llm_client

router = APIRouter(prefix="/config", tags=["配置管理"])


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default: Optional[DefaultLLMConfig] = None
    agents: Optional[Dict[str, AgentConfig]] = None


class TestConnectionResponse(BaseModel):
    """测试连接响应"""
    success: bool
    message: str
    response: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


@router.get("", summary="获取当前配置")
async def get_config() -> Dict[str, Any]:
    """获取当前 LLM 配置"""
    settings = config_manager.llm_settings
    # 隐藏 API Key 的中间部分
    masked_key = ""
    if settings.api_key:
        key = settings.api_key
        if len(key) > 10:
            masked_key = key[:6] + "*" * (len(key) - 10) + key[-4:]
        else:
            masked_key = "*" * len(key)
    
    return {
        "api_key_masked": masked_key,
        "api_key_configured": bool(settings.api_key),
        "base_url": settings.base_url,
        "default": settings.default.model_dump(),
        "agents": {k: v.model_dump() for k, v in settings.agents.items()},
    }


@router.put("", summary="更新配置")
async def update_config(request: UpdateConfigRequest) -> Dict[str, Any]:
    """更新 LLM 配置"""
    current = config_manager.llm_settings
    
    # 更新配置
    if request.api_key is not None:
        current.api_key = request.api_key
    if request.base_url is not None:
        current.base_url = request.base_url
    if request.default is not None:
        current.default = request.default
    if request.agents is not None:
        current.agents.update(request.agents)
    
    # 保存配置
    config_manager.update_llm_settings(current)
    
    return {"success": True, "message": "配置已保存"}


@router.post("/test", summary="测试 API 连接")
async def test_connection() -> TestConnectionResponse:
    """测试 LLM API 连接"""
    if not config_manager.is_configured():
        return TestConnectionResponse(
            success=False,
            message="API Key 未配置，请先设置 API Key"
        )
    
    result = await llm_client.test_connection()
    return TestConnectionResponse(**result)


@router.post("/reset", summary="重置为默认配置")
async def reset_config() -> Dict[str, Any]:
    """重置配置为默认值（保留 API Key）"""
    current = config_manager.llm_settings
    api_key = current.api_key
    base_url = current.base_url
    
    # 创建新的默认配置
    new_settings = LLMSettings(api_key=api_key, base_url=base_url)
    config_manager.update_llm_settings(new_settings)
    
    return {"success": True, "message": "配置已重置为默认值"}


@router.get("/models", summary="获取可用模型列表")
async def get_available_models() -> Dict[str, Any]:
    """获取可用的模型列表"""
    # 阿里云百炼支持的主要模型
    models = [
        {"id": "qwen3-max-preview", "name": "Qwen3 Max Preview", "description": "通义千问3预览版，更强推理能力"},
        {"id": "qwen3-max", "name": "Qwen3 Max", "description": "通义千问3最强模型，支持思考模式"},
        {"id": "qwen3-plus", "name": "Qwen3 Plus", "description": "通义千问3增强版"},
        {"id": "qwen-max", "name": "Qwen Max", "description": "通义千问旗舰模型"},
        {"id": "qwen-plus", "name": "Qwen Plus", "description": "通义千问增强版"},
        {"id": "qwen-turbo", "name": "Qwen Turbo", "description": "通义千问快速版，成本更低"},
    ]
    return {"models": models}


@router.get("/agents", summary="获取 Agent 列表")
async def get_agent_list() -> Dict[str, Any]:
    """获取所有 Agent 及其描述"""
    agents = [
        {"id": "default", "name": "默认配置", "description": "所有 Agent 的基础配置"},
        {"id": "router", "name": "Router Agent", "description": "意图识别，路由用户请求"},
        {"id": "data", "name": "Data Agent", "description": "数据处理和知识库构建"},
        {"id": "clarification", "name": "Clarification Agent", "description": "问题澄清和结构化"},
        {"id": "center", "name": "Center Agent", "description": "报告规划和章节设计"},
        {"id": "research", "name": "Research Agent", "description": "数据研究和章节生成"},
        {"id": "nl2sql", "name": "NL2SQL Agent", "description": "自然语言转 SQL 查询"},
        {"id": "chart", "name": "Chart Agent", "description": "图表配置生成"},
        {"id": "summary", "name": "Summary Agent", "description": "报告引言和结论生成"},
    ]
    return {"agents": agents}

