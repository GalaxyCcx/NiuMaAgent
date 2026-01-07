"""
Agent 事件管理器
用于收集和分发 Agent 调用过程中的事件
"""
import asyncio
import time
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class AgentEvent:
    """Agent 事件"""
    agent_id: str           # 唯一标识 (如 "research_0", "chart_1")
    agent_type: str         # Agent 类型 (router, center, research, nl2sql, chart, summary, data)
    agent_label: str        # 显示名称 (如 "章节1: 市场规模")
    event_type: str         # 事件类型 (start, request, chunk, response, tool_call, tool_result, complete, error)
    timestamp: str          # ISO 时间戳
    data: Dict[str, Any]    # 事件数据
    session_id: str = ""    # 会话 ID
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "agent_event",
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "agent_label": self.agent_label,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class AgentEventManager:
    """Agent 事件管理器 - 单例模式"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 每个 session 的事件队列
        self._queues: Dict[str, asyncio.Queue] = {}
        # 当前活跃的 agents
        self._active_agents: Dict[str, Dict[str, Any]] = {}
        # Agent ID 计数器
        self._agent_counters: Dict[str, int] = {}
        # 锁
        self._lock = asyncio.Lock()
    
    def get_queue(self, session_id: str) -> asyncio.Queue:
        """获取或创建 session 的事件队列"""
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]
    
    def remove_queue(self, session_id: str):
        """移除 session 的事件队列"""
        if session_id in self._queues:
            del self._queues[session_id]
    
    def generate_agent_id(self, agent_type: str) -> str:
        """生成唯一的 Agent ID"""
        if agent_type not in self._agent_counters:
            self._agent_counters[agent_type] = 0
        self._agent_counters[agent_type] += 1
        return f"{agent_type}_{self._agent_counters[agent_type]}"
    
    def reset_counters(self, session_id: str = None):
        """重置 Agent 计数器"""
        self._agent_counters = {}
        if session_id:
            self._active_agents = {k: v for k, v in self._active_agents.items() 
                                   if v.get("session_id") != session_id}
    
    async def emit(self, event: AgentEvent):
        """发射事件到对应的队列"""
        session_id = event.session_id
        if session_id and session_id in self._queues:
            await self._queues[session_id].put(event)
        
        # 更新活跃 agents
        if event.event_type == "start":
            self._active_agents[event.agent_id] = {
                "agent_type": event.agent_type,
                "agent_label": event.agent_label,
                "status": "running",
                "session_id": session_id,
            }
        elif event.event_type in ("complete", "error"):
            if event.agent_id in self._active_agents:
                self._active_agents[event.agent_id]["status"] = event.event_type
    
    def get_active_agents(self, session_id: str = None) -> Dict[str, Dict[str, Any]]:
        """获取活跃的 Agents"""
        if session_id:
            return {k: v for k, v in self._active_agents.items() 
                    if v.get("session_id") == session_id}
        return self._active_agents.copy()


# 全局单例
agent_event_manager = AgentEventManager()


class AgentContext:
    """Agent 上下文管理器 - 用于自动发送 start/complete 事件"""
    
    def __init__(
        self,
        agent_type: str,
        agent_label: str,
        session_id: str,
        agent_id: str = None,
    ):
        self.agent_type = agent_type
        self.agent_label = agent_label
        self.session_id = session_id
        self.agent_id = agent_id or agent_event_manager.generate_agent_id(agent_type)
        self.start_time = None
    
    async def __aenter__(self):
        self.start_time = time.time()
        await self.emit("start", {})
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time if self.start_time else 0
        if exc_type:
            await self.emit("error", {
                "error": str(exc_val),
                "duration": f"{duration:.2f}s",
            })
        else:
            await self.emit("complete", {
                "duration": f"{duration:.2f}s",
            })
        return False
    
    async def emit(self, event_type: str, data: Dict[str, Any]):
        """发射事件 - 确保不影响主流程"""
        try:
            event = AgentEvent(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                agent_label=self.agent_label,
                event_type=event_type,
                timestamp=datetime.now().isoformat(),
                data=data,
                session_id=self.session_id,
            )
            await agent_event_manager.emit(event)
        except Exception as e:
            # 事件发射失败不应影响主流程
            print(f"[AgentEvent] 发射事件失败: {e}")
    
    async def emit_request(self, messages: List[Dict[str, Any]]):
        """发射请求事件 - 完整内容"""
        # 显示所有 messages，不截断
        simplified = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            entry = {"role": role, "content": content}
            if tool_calls:
                entry["tool_calls"] = [tc.get("function", {}).get("name", "") for tc in tool_calls]
            simplified.append(entry)
        
        await self.emit("request", {
            "messages_count": len(messages),
            "messages": simplified,  # 完整消息列表
        })
    
    async def emit_chunk(self, chunk: str, chunk_type: str = "content"):
        """发射 chunk 事件 - 完整内容"""
        await self.emit("chunk", {
            "content": chunk,
            "type": chunk_type,
        })
    
    async def emit_response(self, content: str = None, tool_calls: List = None):
        """发射响应事件 - 完整内容"""
        data = {}
        if content:
            data["content"] = content  # 完整内容
            data["content_length"] = len(content)
        if tool_calls:
            data["tool_calls"] = [
                {
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "arguments": tc.get("function", {}).get("arguments", ""),
                }
                for tc in tool_calls
            ]
        await self.emit("response", data)
    
    async def emit_tool_call(self, tool_name: str, arguments: Dict[str, Any]):
        """发射工具调用事件 - 完整内容"""
        await self.emit("tool_call", {
            "name": tool_name,
            "arguments": arguments,  # 完整参数
        })
    
    async def emit_tool_result(self, tool_name: str, result_summary: str):
        """发射工具结果事件 - 完整内容"""
        await self.emit("tool_result", {
            "name": tool_name,
            "summary": result_summary,  # 完整内容
        })

