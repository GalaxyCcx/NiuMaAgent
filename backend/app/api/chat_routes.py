"""
对话 API 路由 - 统一对话入口
支持：简单问题直接回答、复杂需求触发报告生成、Clarification 交互
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, AsyncGenerator
import json
import math
import traceback
import asyncio

from ..config import config_manager
from ..services.agent_events import agent_event_manager, AgentEvent


def _clean_nan(obj):
    """
    递归清理 NaN、Infinity 等不能 JSON 序列化的值
    """
    if obj is None:
        return None
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(_clean_nan(item) for item in obj)
    else:
        return obj


async def pass_through_events(
    session_id: str,
    main_generator: AsyncGenerator[Dict[str, Any], None],
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    直接传递主事件流，不再混入 Agent 事件
    Agent 事件现在通过独立的 /monitor/{session_id} 端点获取
    """
    try:
        async for event in main_generator:
            yield event
    except Exception as e:
        print(f"[PassThrough] 主生成器错误: {e}")
        import traceback
        traceback.print_exc()
        yield {"type": "error", "message": str(e)}
    finally:
        # 清理队列
        agent_event_manager.remove_queue(session_id)


def safe_json_dumps(obj, **kwargs):
    """
    安全的 JSON 序列化，自动处理 NaN 等非法值
    """
    try:
        cleaned = _clean_nan(obj)
        return json.dumps(cleaned, **kwargs)
    except Exception as e:
        print(f"[JSON] 序列化失败: {e}")
        traceback.print_exc()
        # 返回错误 JSON
        return json.dumps({"type": "error", "error": f"JSON序列化失败: {str(e)}"}, **kwargs)
from ..llm import llm_client
from ..models.session import session_manager
from ..services.chat_agent import chat_agent
from ..services.report import center_agent

router = APIRouter(prefix="/chat", tags=["对话"])


class ChatMessage(BaseModel):
    """聊天消息"""
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    session_id: str
    message: str
    history: Optional[List[ChatMessage]] = None
    stream: bool = False
    # Clarification 相关
    clarification_response: Optional[str] = None  # 用户对 Clarification 的回复
    original_request: Optional[str] = None  # 原始报告需求（当回复 Clarification 时）
    messages_context: Optional[List[dict]] = None  # LLM 对话上下文（用于恢复 Clarification 会话）
    tool_call_id: Optional[str] = None  # Clarification 工具调用 ID


class ChatResponse(BaseModel):
    """聊天响应"""
    content: str
    role: str = "assistant"
    analysis: Optional[str] = None
    sql: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class SimpleChatRequest(BaseModel):
    """简单聊天请求（无上下文）"""
    messages: List[ChatMessage]
    agent: str = "default"
    stream: bool = False


@router.post("/data", summary="统一对话入口")
async def chat_with_data(request: ChatRequest):
    """
    统一对话入口 - 自动识别意图
    
    - 简单问题：直接对话回答
    - 复杂需求：触发报告生成流程
    - Clarification：返回澄清问题让用户确认
    """
    if not config_manager.is_configured():
        raise HTTPException(
            status_code=400,
            detail="API Key 未配置，请先在配置页面设置 API Key"
        )
    
    # 获取会话
    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 转换历史消息格式
    history = []
    if request.history:
        history = [{"role": m.role, "content": m.content} for m in request.history]
    
    # 流式响应（统一处理）
    async def generate():
        try:
            # 检查是否是 Clarification 回复
            if request.clarification_response and request.original_request:
                print(f"[Chat] Clarification 回复，继续报告生成")
                print(f"  原始需求: {request.original_request[:50]}...")
                print(f"  用户回复: {request.clarification_response[:100]}...")
                print(f"  有 messages_context: {request.messages_context is not None}")
                print(f"  有 tool_call_id: {request.tool_call_id is not None}")
                
                yield f"data: {safe_json_dumps({'type': 'intent', 'intent': 'report', 'message': '收到您的回复，继续生成报告...'}, ensure_ascii=False)}\n\n"
                
                # 构建 clarification_context
                clarification_context = {
                    "messages_context": request.messages_context,
                    "tool_call_id": request.tool_call_id,
                    "user_response": request.clarification_response,
                }
                
                # 使用合并事件流
                main_gen = center_agent.generate_report(
                    session=session,
                    user_request=request.original_request,
                    stream=True,
                    clarification_context=clarification_context,
                )
                
                async for event in pass_through_events(session.session_id, main_gen):
                    event_type = event.get("type", "unknown")
                    
                    # agent_event 类型特殊处理
                    if event_type == "agent_event":
                        event_json = safe_json_dumps(event, ensure_ascii=False)
                        yield f"data: {event_json}\n\n"
                        continue
                    
                    print(f"[Chat] 收到事件: {event_type}")
                    
                    # 详细日志：complete 事件
                    if event_type == "complete":
                        report = event.get("report", {})
                        print(f"[Chat] 报告完成!")
                        print(f"  report_id: {report.get('report_id')}")
                        print(f"  title: {report.get('title')}")
                        print(f"  sections: {len(report.get('sections', []))}")
                    
                    # 如果再次需要 Clarification
                    if event_type == "clarification":
                        yield f"data: {safe_json_dumps({'type': 'clarification', 'rewritten_request': event.get('rewritten_request', ''), 'original_intent': event.get('original_intent', ''), 'original_request': request.original_request, 'messages_context': event.get('messages_context'), 'tool_call_id': event.get('tool_call_id')}, ensure_ascii=False)}\n\n"
                        return
                    
                    # 安全序列化并发送
                    event_json = safe_json_dumps(event, ensure_ascii=False)
                    print(f"[Chat] 发送事件: {event_type}, 长度: {len(event_json)}")
                    yield f"data: {event_json}\n\n"
                
                print(f"[Chat] 发送 [DONE]")
                yield "data: [DONE]\n\n"
                return
            
            # Step 1: 意图识别
            intent = await identify_intent(request.message, session)
            print(f"[Chat] 意图识别: {intent}")
            
            if intent == "report":
                # 复杂需求 -> 报告生成流程
                yield f"data: {safe_json_dumps({'type': 'intent', 'intent': 'report', 'message': '检测到报告生成需求，开始规划...'}, ensure_ascii=False)}\n\n"
                
                # 使用合并事件流
                main_gen = center_agent.generate_report(
                    session=session,
                    user_request=request.message,
                    stream=True,
                )
                
                async for event in pass_through_events(session.session_id, main_gen):
                    event_type = event.get("type", "unknown")
                    
                    # agent_event 类型特殊处理
                    if event_type == "agent_event":
                        event_json = safe_json_dumps(event, ensure_ascii=False)
                        yield f"data: {event_json}\n\n"
                        continue
                    
                    print(f"[Chat] 收到事件: {event_type}")
                    
                    # 详细日志：complete 事件
                    if event_type == "complete":
                        report = event.get("report", {})
                        print(f"[Chat] 报告完成!")
                        print(f"  report_id: {report.get('report_id')}")
                        print(f"  title: {report.get('title')}")
                        print(f"  sections: {len(report.get('sections', []))}")
                    
                    # 处理 Clarification - 需要用户确认改写后的需求
                    if event_type == "clarification":
                        # 传递改写内容和对话上下文，以便前端在确认时带回
                        clarification_data = {
                            'type': 'clarification',
                            'rewritten_request': event.get('rewritten_request', ''),
                            'original_intent': event.get('original_intent', ''),
                            'original_request': request.message,
                            'messages_context': event.get('messages_context'),  # LLM 对话上下文
                            'tool_call_id': event.get('tool_call_id'),  # 工具调用 ID
                        }
                        print(f"[Chat] 发送 Clarification 到前端:")
                        print(f"  rewritten_request: {clarification_data['rewritten_request'][:100]}...")
                        print(f"  has messages_context: {clarification_data['messages_context'] is not None}")
                        print(f"  tool_call_id: {clarification_data['tool_call_id']}")
                        yield f"data: {safe_json_dumps(clarification_data, ensure_ascii=False)}\n\n"
                        return  # 等待用户确认
                    
                    # 安全序列化并发送
                    event_json = safe_json_dumps(event, ensure_ascii=False)
                    print(f"[Chat] 发送事件: {event_type}, 长度: {len(event_json)}")
                    yield f"data: {event_json}\n\n"
            else:
                # 简单问题 -> 直接对话
                yield f"data: {safe_json_dumps({'type': 'intent', 'intent': 'chat', 'message': ''}, ensure_ascii=False)}\n\n"
                
                async for chunk in chat_agent.chat_stream(
                    session=session,
                    user_message=request.message,
                    history=history,
                ):
                    yield f"data: {safe_json_dumps(chunk, ensure_ascii=False)}\n\n"
            
            print(f"[Chat] 发送 [DONE]")
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            print(f"[Chat] 错误: {e}")
            traceback.print_exc()
            yield f"data: {safe_json_dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def identify_intent(message: str, session) -> str:
    """
    意图识别：判断是简单问题还是报告生成需求
    
    判断标准：
    1. 用户是否明确要求生成"报告"或"深度分析"？
    2. 用户的需求是否能用 1-2 条 SQL 解决（如：求平均值、对比差异、查询列表）？
    3. 用户需求是否涉及多个维度、多个分析步骤？
    
    Returns:
        "chat": 简单问题，直接对话（可通过 SQL 查询解决）
        "report": 复杂需求，触发报告生成
    """
    message_lower = message.lower()
    
    # 明确的报告关键词 - 用户明确要求报告
    explicit_report_keywords = [
        "报告", "分析报告", "生成报告", "出一份报告", "写一份报告",
        "深度分析", "全面分析", "详细分析", "整体分析", "综合分析",
        "多维度分析", "系统分析", "完整分析",
    ]
    
    # 明确要求报告时，直接返回 report
    for keyword in explicit_report_keywords:
        if keyword in message_lower:
            print(f"[意图识别] 匹配报告关键词: {keyword} -> report")
            return "report"
    
    # 简单查询的特征词 - 这些通常只需要 SQL 查询
    simple_query_patterns = [
        "查一下", "查询", "看看", "列出", "显示", "告诉我",
        "是什么", "有哪些", "多少", "几个", "什么是",
        "平均值", "最大值", "最小值", "总数", "数量",
        "比较", "差异", "对比一下",  # 简单对比也是查询
        "非空", "为空", "等于", "大于", "小于",
    ]
    
    # 检查是否包含简单查询特征
    has_simple_pattern = any(p in message_lower for p in simple_query_patterns)
    
    # 如果包含简单查询模式，且不包含复杂分析词，倾向于 chat
    complex_analysis_words = [
        "趋势", "发展", "变化规律", "演变", "市场格局",
        "多角度", "多方面", "全方位", "洞察", "研究",
    ]
    has_complex_words = any(w in message_lower for w in complex_analysis_words)
    
    if has_simple_pattern and not has_complex_words:
        print(f"[意图识别] 简单查询模式 -> chat")
        return "chat"
    
    # 对于不确定的情况，使用 LLM 判断
    try:
        result = await llm_client.chat(
            messages=[{
                "role": "user",
                "content": f"""判断用户需求是"简单查询"还是"复杂报告"。

用户消息：{message}

判断标准：
- "chat"（简单查询）：能用 1-2 条 SQL 解决的问题
  例如：
  - "查一下xxx的数量" -> chat
  - "比较A和B的平均值差异" -> chat
  - "support_url非空和为空的游戏数量对比" -> chat
  - "列出评分最高的10款游戏" -> chat
  - "某字段的平均值是多少" -> chat

- "report"（复杂报告）：需要多步骤、多维度分析的需求
  例如：
  - "分析游戏市场的发展趋势" -> report
  - "做一份开发商表现的分析报告" -> report
  - "研究不同类型游戏的用户偏好变化" -> report
  - "全面对比各平台的市场份额" -> report

请只回复 "chat" 或 "report"，不要解释。"""
            }],
            agent_name="router",
            stream=False,
        )
        
        intent = result.get("content", "").strip().lower()
        # 清理可能的思考标签
        if "<think>" in intent:
            intent = intent.split("</think>")[-1].strip()
        
        if "report" in intent:
            print(f"[意图识别] LLM 判断 -> report")
            return "report"
        print(f"[意图识别] LLM 判断 -> chat")
        return "chat"
        
    except Exception as e:
        print(f"[意图识别] LLM 调用失败: {e}")
        # 默认为简单对话
        return "chat"


@router.get("/suggest/{session_id}", summary="获取推荐问题")
async def get_suggested_questions(session_id: str, limit: int = 5):
    """
    获取基于数据的推荐问题
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    try:
        questions = await chat_agent.suggest_questions(session, limit)
        return {"questions": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", summary="执行数据查询")
async def execute_query(session_id: str, sql: str):
    """
    直接执行 SQL 查询
    """
    from ..services.data_executor import data_executor
    
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    success, data, message = data_executor.execute_sql(session, sql)
    
    if success:
        return {"success": True, "data": data, "message": message}
    else:
        return {"success": False, "data": None, "message": message}


@router.post("", summary="通用对话（无数据上下文）")
async def simple_chat(request: SimpleChatRequest):
    """
    简单对话接口，不注入数据上下文
    
    - 支持多轮对话
    - 支持指定 Agent
    - 支持流式/非流式响应
    """
    if not config_manager.is_configured():
        raise HTTPException(
            status_code=400,
            detail="API Key 未配置，请先在配置页面设置 API Key"
        )
    
    # 转换消息格式
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    
    if request.stream:
        # 流式响应
        async def generate():
            try:
                async for chunk in await llm_client.chat(
                    messages=messages,
                    agent_name=request.agent,
                    stream=True,
                ):
                    yield f"data: {safe_json_dumps({'content': chunk})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {safe_json_dumps({'error': str(e)})}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    else:
        # 非流式响应
        try:
            result = await llm_client.chat(
                messages=messages,
                agent_name=request.agent,
                stream=False,
            )
            return ChatResponse(
                content=result["content"] or "",
                role=result["role"],
                usage=result["usage"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# ========== 独立监控 API ==========

@router.get("/monitor/{session_id}")
async def monitor_stream(session_id: str):
    """
    独立的监控 SSE 流
    只推送 agent 事件，不影响主聊天流
    """
    async def generate():
        queue = agent_event_manager.get_queue(session_id)
        
        try:
            while True:
                try:
                    # 等待事件，超时发心跳
                    event = await asyncio.wait_for(queue.get(), timeout=3.0)
                    
                    if event is None:
                        # 结束信号
                        break
                    
                    if isinstance(event, AgentEvent):
                        event_data = _clean_nan(event.to_dict())
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    
                except asyncio.TimeoutError:
                    # 心跳
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
