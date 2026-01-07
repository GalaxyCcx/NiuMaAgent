"""
配置管理模块
支持 LLM 配置的持久化存储和动态更新
"""
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class AgentConfig(BaseModel):
    """单个 Agent 的配置"""
    model: Optional[str] = None  # None 表示使用默认配置
    enable_thinking: Optional[bool] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None


class DefaultLLMConfig(BaseModel):
    """默认 LLM 配置"""
    model: str = "qwen3-max"
    enable_thinking: bool = True
    max_tokens: int = 8192
    temperature: float = 0.7
    top_p: float = 0.9


class LLMSettings(BaseModel):
    """LLM 完整配置"""
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default: DefaultLLMConfig = Field(default_factory=DefaultLLMConfig)
    agents: Dict[str, AgentConfig] = Field(default_factory=lambda: {
        "router": AgentConfig(temperature=0.3, enable_thinking=False),
        "data": AgentConfig(temperature=0.5),
        "clarification": AgentConfig(temperature=0.7),
        "center": AgentConfig(temperature=0.7, model="qwen3-max-preview"),
        "research": AgentConfig(enable_thinking=True, max_tokens=16384, model="qwen3-max-preview"),
        "nl2sql": AgentConfig(temperature=0.3, enable_thinking=False),  # SQL 生成需要精确，低温度
        "chart": AgentConfig(temperature=0.3, enable_thinking=False),
        "summary": AgentConfig(temperature=0.7),
    })


class AppSettings(BaseSettings):
    """应用配置"""
    app_name: str = "Chat2Excel"
    debug: bool = True
    data_dir: str = "../data"  # 相对于 backend 目录
    config_file: str = "../data/config.json"
    
    class Config:
        env_prefix = "DEEPRESEARCH_"


class ConfigManager:
    """配置管理器 - 负责配置的加载、保存和获取"""
    
    _instance: Optional["ConfigManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.app_settings = AppSettings()
        self.llm_settings: Optional[LLMSettings] = None
        self._ensure_data_dir()
        self._load_config()
    
    def _ensure_data_dir(self):
        """确保数据目录存在"""
        Path(self.app_settings.data_dir).mkdir(parents=True, exist_ok=True)
    
    def _load_config(self):
        """从文件加载配置"""
        config_path = Path(self.app_settings.config_file)
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.llm_settings = LLMSettings(**data)
            except Exception as e:
                print(f"加载配置失败: {e}, 使用默认配置")
                self.llm_settings = LLMSettings()
        else:
            self.llm_settings = LLMSettings()
    
    def save_config(self):
        """保存配置到文件"""
        config_path = Path(self.app_settings.config_file)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self.llm_settings.model_dump(), f, ensure_ascii=False, indent=2)
    
    def update_llm_settings(self, settings: LLMSettings):
        """更新 LLM 配置"""
        self.llm_settings = settings
        self.save_config()
    
    def get_agent_config(self, agent_name: str) -> Dict[str, Any]:
        """获取指定 Agent 的完整配置（合并默认配置）"""
        default = self.llm_settings.default.model_dump()
        agent = self.llm_settings.agents.get(agent_name, AgentConfig()).model_dump()
        
        # 合并配置，agent 配置覆盖默认配置
        merged = default.copy()
        for key, value in agent.items():
            if value is not None:
                merged[key] = value
        
        return merged
    
    def get_llm_client_config(self) -> Dict[str, str]:
        """获取 LLM 客户端配置"""
        return {
            "api_key": self.llm_settings.api_key,
            "base_url": self.llm_settings.base_url,
        }
    
    def is_configured(self) -> bool:
        """检查是否已配置 API Key"""
        return bool(self.llm_settings.api_key)


# 全局配置管理器实例
config_manager = ConfigManager()

