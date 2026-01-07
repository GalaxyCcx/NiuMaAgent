"""
Center Agent - 报告中心协调 Agent
负责：理解用户需求、规划报告章节、协调并发执行
"""
import json
import uuid
import asyncio
import time
from typing import Dict, List, Any, Optional, AsyncGenerator
from datetime import datetime
from pathlib import Path

from ...llm import llm_client
from ...models.session import Session
from ..context_builder import context_builder
from ..agent_events import AgentContext, agent_event_manager
from .researcher_agent import ResearcherAgent
from .summary_agent import summary_agent


# Center Agent 工具定义 - 与 Center-tools04-0928.json 保持一致
CENTER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Clarification",
            "description": "将用户问题进行澄清，进行更结构化的表达，并要求用户进行细节确认",
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "改写后的结构化分析请求（Markdown格式），包含分析目标、分析维度、下钻要求、输出要求、关键参数等"
                    }
                },
                "required": ["requirement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Sections",
            "description": "生成包含动态参数配置和详细章节结构的完整报告框架",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "报告的核心主题/标题"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "完全自定义的关键分析维度参数，模型自行决定参数名称和值",
                        "additionalProperties": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "object", "additionalProperties": True}
                            ]
                        }
                    },
                    "sections": {
                        "type": "array",
                        "description": "结构化报告章节设计",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "章节报告的这一章节的标题/名称标题"
                                },
                                "research_description": {
                                    "type": "string",
                                    "description": "详细说明应在这一部分研究和涵盖的内容（5-7句话）"
                                },
                                "analysis_method": {
                                    "type": "string",
                                    "description": "具体应使用哪些分析或比较方法（例如：'比较分析'、'技术深度剖析'、'案例研究分析'、'优缺点评估'）"
                                },
                                "key_parameters": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "本部分必须涵盖的关键参数、指标或具体的关键信息的列表"
                                },
                                "research_focus": {
                                    "type": "string",
                                    "description": "本部分研究的重点（例如：'市场趋势'、'技术发展'、'竞争对手分析'、'用户需求'）"
                                }
                            },
                            "required": ["title", "research_description", "analysis_method", "key_parameters", "research_focus"]
                        }
                    }
                },
                "required": ["topic", "parameters", "sections"]
            }
        }
    }
]


def load_center_prompt() -> str:
    """加载 Center Agent 系统提示词"""
    prompt_path = Path(__file__).parent.parent.parent.parent.parent / "prompt" / "Center-Agent04-0928"
    
    if prompt_path.exists():
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    
    # 如果文件不存在，使用内置提示词
    return """你是报告规划专家。根据用户需求和数据知识库，规划报告结构。

## 工作流程（严格按顺序执行）
1. 理解用户需求：分析用户想要什么样的报告
2. 需求澄清（仅一次）：调用 Clarification 工具，将用户的非结构化需求改写为清晰完整的结构化分析请求
3. 用户确认后：**立即**调用 Sections 工具定义报告结构（不再调用 Clarification）

## ⚠️ 重要约束
- **Clarification 只能调用一次**
- 当收到用户对 Clarification 的确认回复后，必须立即调用 Sections 工具
- 不得重复调用 Clarification

## Clarification 输出格式
改写后的请求应包含：
- 分析目标：明确的分析目的
- 分析维度：具体的分析角度（从知识库获取）
- 下钻要求：分析粒度和层级
- 输出要求：需要回答的问题列表
- 关键参数：时间范围、筛选条件等

## 章节规划原则
- 每个章节应该有明确的分析目标
- 章节之间应该有逻辑递进关系
- 通常包括：概览 → 细分分析 → 归因分析 → 建议

## 输出要求
- 首次交互调用 Clarification 工具改写需求
- 用户确认后立即调用 Sections 工具输出章节规划
- 章节数量通常 3-5 个为宜
"""


def load_clarification_prompt() -> str:
    """加载 Clarification 提示词"""
    prompt_path = Path(__file__).parent.parent.parent.parent.parent / "prompt" / "Clarification"
    
    if prompt_path.exists():
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    
    return ""


class CenterAgent:
    """Center Agent - 报告中心协调"""
    
    def __init__(self):
        self.researcher_agents: Dict[str, ResearcherAgent] = {}
    
    async def generate_report(
        self,
        session: Session,
        user_request: str,
        stream: bool = True,
        clarification_context: Optional[Dict[str, Any]] = None,  # 新增：Clarification 上下文
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        生成报告（流式）
        
        Args:
            session: 用户会话
            user_request: 用户的报告需求
            stream: 是否流式返回
            clarification_context: Clarification 的上下文（用于恢复对话）
        
        Yields:
            各种进度和结果事件
        """
        report_id = str(uuid.uuid4())
        
        # 重置事件计数器
        agent_event_manager.reset_counters(session.session_id)
        
        # 创建 Center Agent 上下文
        self.agent_ctx = AgentContext(
            agent_type="center",
            agent_label="Center: 报告协调",
            session_id=session.session_id,
        )
        
        yield {
            "type": "report_created",
            "report_id": report_id,
            "timestamp": datetime.now().isoformat(),
        }
        
        try:
            # 发射 Center Agent start 事件
            await self.agent_ctx.emit("start", {"report_id": report_id})
            
            # Step 1: 构建知识上下文
            yield {"type": "status", "message": "正在分析数据知识库..."}
            
            knowledge = context_builder.build_knowledge_context(session)
            if not knowledge:
                yield {
                    "type": "error",
                    "message": "没有可用的数据知识库，请先上传数据文件",
                }
                return
            
            # Step 2: 调用 Center Agent 规划章节
            yield {"type": "status", "message": "正在规划报告结构..."}
            
            outline = await self._plan_sections(
                session=session,
                user_request=user_request,
                knowledge=knowledge,
                clarification_context=clarification_context,  # 传递上下文
            )
            
            if outline.get("clarification"):
                # 需要用户确认改写后的需求
                yield {
                    "type": "clarification",
                    "rewritten_request": outline["clarification"]["rewritten_request"],
                    "original_intent": outline["clarification"].get("original_intent", ""),
                    "messages_context": outline.get("messages_context"),  # 保存对话上下文
                    "tool_call_id": outline.get("tool_call_id"),  # 保存 tool_call_id
                }
                return
            
            if "error" in outline:
                yield {"type": "error", "message": outline["error"]}
                return
            
            yield {
                "type": "outline",
                "data": outline,
            }
            
            # Step 3: 并发执行各章节研究
            sections = outline.get("sections", [])
            total_sections = len(sections)
            
            yield {"type": "status", "message": f"开始并发执行 {total_sections} 个章节研究..."}
            
            # 发送章节开始事件，让前端显示进度
            for i, section_def in enumerate(sections):
                yield {
                    "type": "section_start",
                    "index": i,
                    "total": total_sections,
                    "title": section_def.get("title", f"章节 {i+1}"),
                }
            
            # 提取全局上下文
            report_context = {
                "topic": outline.get("topic", outline.get("report_title", "数据分析报告")),
                "parameters": outline.get("parameters", {}),
            }
            
            # 创建研究任务
            async def research_section(section_def: dict, index: int):
                """研究单个章节"""
                researcher = ResearcherAgent()
                
                try:
                    result = await researcher.research_section(
                        session=session,
                        section_definition=section_def,
                        report_context=report_context,  # 传递全局上下文
                        knowledge=knowledge,
                        date=datetime.now().strftime("%Y-%m-%d"),
                    )
                    return {
                        "index": index,
                        "section_id": section_def["section_id"],
                        "success": True,
                        "result": result,
                    }
                except Exception as e:
                    print(f"章节研究失败: {e}")
                    import traceback
                    traceback.print_exc()
                    return {
                        "index": index,
                        "section_id": section_def["section_id"],
                        "success": False,
                        "error": str(e),
                    }
            
            # 并发执行
            task_map = {}  # task -> index
            for i, section_def in enumerate(sections):
                task = asyncio.create_task(research_section(section_def, i))
                task_map[task] = i
            
            print(f"[CenterAgent] 创建了 {len(task_map)} 个并发任务")
            
            completed_sections = []
            completed_count = 0
            pending = set(task_map.keys())
            heartbeat_interval = 15  # 每15秒发送一次心跳
            last_heartbeat = time.time()
            
            # 使用 asyncio.wait 配合超时来定期发送心跳
            while pending:
                # 等待任务完成或超时
                done, pending = await asyncio.wait(
                    pending,
                    timeout=heartbeat_interval,
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 处理完成的任务
                for task in done:
                    try:
                        result = task.result()
                        completed_count += 1
                        print(f"[CenterAgent] 任务完成: index={result['index']}, success={result['success']}")
                        
                        if result["success"]:
                            section_data = result["result"].get("section", {})
                            completed_sections.append({
                                "index": result["index"],
                                "section": section_data,
                            })
                            
                            print(f"[CenterAgent] 发送 section_complete 事件: {result['index']}")
                            yield {
                                "type": "section_complete",
                                "index": result["index"],
                                "total": total_sections,
                                "section": section_data,
                            }
                        else:
                            print(f"[CenterAgent] 发送 section_error 事件: {result['index']}, error={result['error']}")
                            yield {
                                "type": "section_error",
                                "index": result["index"],
                                "error": result["error"],
                            }
                    except Exception as e:
                        print(f"[CenterAgent] 任务异常: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 如果有待完成的任务，发送心跳
                if pending and time.time() - last_heartbeat >= heartbeat_interval - 1:
                    yield {
                        "type": "heartbeat",
                        "message": f"正在处理... ({completed_count}/{total_sections} 章节完成, 还有 {len(pending)} 个任务)",
                        "completed": completed_count,
                        "total": total_sections,
                        "pending": len(pending),
                    }
                    last_heartbeat = time.time()
            
            print(f"[CenterAgent] 所有章节完成，开始组装报告")
            print(f"[CenterAgent] 完成的章节数: {len(completed_sections)}")
            
            # 按原始顺序排序
            completed_sections.sort(key=lambda x: x["index"])
            
            # Step 4: 生成引言和总结
            yield {"type": "status", "message": "正在生成引言和总结..."}
            
            # 收集各章节结论
            sections_conclusions = []
            for cs in completed_sections:
                section = cs.get("section", {})
                sections_conclusions.append({
                    "name": section.get("name", f"章节 {cs['index']+1}"),
                    "conclusion": section.get("conclusion", "")
                })
            
            # 获取 Clarification 确认内容
            clarification_content = None
            if clarification_context:
                clarification_content = clarification_context.get("user_response", "")
            
            # 调用 Summary Agent
            summary_result = await summary_agent.generate_summary(
                user_request=user_request,
                topic=outline.get("topic", outline.get("report_title", "数据分析报告")),
                parameters=outline.get("parameters", {}),
                sections_conclusions=sections_conclusions,
                clarification_content=clarification_content,
                session_id=session.session_id,  # 传入 session_id 用于事件追踪
            )
            
            introduction = summary_result.get("introduction", "")
            summary_and_recommendations = summary_result.get("summary_and_recommendations", "")
            
            print(f"[CenterAgent] 引言和总结生成完成")
            print(f"  引言长度: {len(introduction)}")
            print(f"  总结长度: {len(summary_and_recommendations)}")
            
            # Step 5: 组装最终报告
            yield {"type": "status", "message": "正在组装报告..."}
            
            # 构建引言章节
            introduction_section = {
                "section_id": "introduction",
                "name": "引言",
                "discoveries": [{
                    "title": "报告概述",
                    "insight": introduction,
                    "charts": []
                }],
                "conclusion": ""
            } if introduction else None
            
            # 构建总结章节
            summary_section = {
                "section_id": "summary",
                "name": "总结与建议",
                "discoveries": [{
                    "title": "核心发现与行动建议",
                    "insight": summary_and_recommendations,
                    "charts": []
                }],
                "conclusion": ""
            } if summary_and_recommendations else None
            
            # 组装所有章节
            all_sections = []
            if introduction_section:
                all_sections.append(introduction_section)
            all_sections.extend([s["section"] for s in completed_sections])
            if summary_section:
                all_sections.append(summary_section)
            
            report = {
                "report_id": report_id,
                "title": outline.get("topic", outline.get("report_title", "数据分析报告")),
                "summary": introduction[:200] if introduction else outline.get("report_summary", ""),
                "sections": all_sections,
                "created_at": datetime.now().isoformat(),
                "status": "completed",
            }
            
            print(f"[CenterAgent] 报告组装完成:")
            print(f"  report_id: {report['report_id']}")
            print(f"  title: {report['title']}")
            print(f"  sections: {len(report['sections'])} (含引言和总结)")
            print(f"[CenterAgent] 发送 complete 事件...")
            
            yield {
                "type": "complete",
                "report": report,
            }
            
            print(f"[CenterAgent] complete 事件已发送")
            
        except Exception as e:
            print(f"报告生成失败: {e}")
            import traceback
            traceback.print_exc()
            yield {
                "type": "error",
                "message": f"报告生成失败: {str(e)}",
            }
    
    async def _plan_sections(
        self,
        session: Session,
        user_request: str,
        knowledge: str,
        clarification_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        规划报告章节
        
        Args:
            clarification_context: 包含 messages_context 和 tool_call_id，以及 user_response
        
        Returns:
            章节规划结果，或 clarification 请求，或 error
        """
        system_prompt = load_center_prompt()
        
        # 检查是否是 Clarification 回复
        if clarification_context and clarification_context.get("messages_context"):
            # 恢复之前的对话上下文
            messages = clarification_context["messages_context"]
            tool_call_id = clarification_context.get("tool_call_id", "clarification_call")
            user_response = clarification_context.get("user_response", "")
            
            print(f"[CenterAgent] 恢复 Clarification 对话上下文")
            print(f"[CenterAgent] 用户回复: {user_response[:100]}...")
            print(f"[CenterAgent] 消息数量: {len(messages)}")
            
            # 添加用户的 Clarification 回复作为 tool 响应
            # 关键：明确告诉模型用户已确认，应该继续调用 Sections
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"""用户已确认需求如下：
{user_response}

【重要】用户已确认上述需求，Clarification 阶段已完成。
请立即调用 Sections 工具，根据上述确认的需求规划报告章节。
不要再次调用 Clarification。"""
            })
            
            # 打印 message list 供调试
            print(f"\n[CenterAgent] === 完整的 Message List ===")
            for i, msg in enumerate(messages):
                role = msg.get("role", "unknown")
                content_preview = str(msg.get("content", ""))[:100]
                tool_calls = msg.get("tool_calls", [])
                print(f"  [{i}] role={role}, content={content_preview}...")
                if tool_calls:
                    for tc in tool_calls:
                        print(f"       tool_call: {tc.get('function', {}).get('name', 'unknown')}")
            print(f"[CenterAgent] === End Message List ===\n")
            
        else:
            # 构建新的用户消息
            user_message = f"""## 用户需求
{user_request}

## 可用数据知识库
{knowledge}

请根据用户需求和数据知识库，规划报告结构。如果需要澄清，调用 Clarification 工具；否则调用 Sections 工具输出章节规划。"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        
        max_iterations = 5
        
        for iteration in range(max_iterations):
            try:
                print(f"[CenterAgent] 迭代 {iteration + 1}/{max_iterations}")
                
                # 发射请求事件
                await self.agent_ctx.emit_request(messages)
                
                # 定义 chunk 回调
                async def on_chunk(chunk: str, chunk_type: str):
                    await self.agent_ctx.emit_chunk(chunk, chunk_type)
                
                result = await llm_client.chat(
                    messages=messages,
                    agent_name="center",
                    tools=CENTER_TOOLS,
                    stream=False,
                    chunk_callback=on_chunk,  # 流式接收 chunk
                )
                
                # 发射响应事件（完整结果）
                await self.agent_ctx.emit_response(
                    content=result.get("content"),
                    tool_calls=result.get("tool_calls"),
                )
                
                if result.get("tool_calls"):
                    for tool_call in result["tool_calls"]:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])
                        tool_call_id = tool_call.get("id", f"call_{iteration}")
                        
                        # 发射工具调用事件
                        await self.agent_ctx.emit_tool_call(tool_name, tool_args)
                        print(f"[CenterAgent] 工具调用: {tool_name}")
                        
                        if tool_name == "Clarification":
                            # 保存当前的消息上下文（包括 assistant 的 tool_call）
                            messages.append({
                                "role": "assistant",
                                "content": result.get("content", ""),
                                "tool_calls": result["tool_calls"],
                            })
                            
                            return {
                                "clarification": {
                                    # 兼容新旧字段名
                                    "rewritten_request": tool_args.get("requirement", tool_args.get("rewritten_request", "")),
                                    "original_intent": tool_args.get("original_intent", ""),
                                },
                                "messages_context": messages,  # 保存上下文
                                "tool_call_id": tool_call_id,  # 保存 tool_call_id
                            }
                        
                        elif tool_name == "Sections":
                            sections = tool_args.get("sections", [])
                            print(f"[CenterAgent] 成功获取章节规划: {len(sections)} 个章节")
                            
                            # 打印详细的章节信息
                            for i, sec in enumerate(sections):
                                print(f"  [{i}] title: {sec.get('title', 'N/A')}")
                                print(f"      research_description: {sec.get('research_description', 'N/A')[:80]}...")
                                print(f"      analysis_method: {sec.get('analysis_method', 'N/A')}")
                                print(f"      key_parameters: {sec.get('key_parameters', [])}")
                                print(f"      research_focus: {sec.get('research_focus', 'N/A')}")
                            
                            # 标准化返回结构，添加兼容字段
                            normalized = {
                                "topic": tool_args.get("topic", "数据分析报告"),
                                "parameters": tool_args.get("parameters", {}),
                                "sections": [],
                                # 兼容旧字段名
                                "report_title": tool_args.get("topic", "数据分析报告"),
                                "report_summary": "",
                            }
                            
                            # 为每个章节添加 section_id 和标准化字段
                            for i, sec in enumerate(sections):
                                normalized_section = {
                                    "section_id": f"section_{i+1}",
                                    "title": sec.get("title", f"章节 {i+1}"),
                                    "research_description": sec.get("research_description", ""),
                                    "analysis_method": sec.get("analysis_method", ""),
                                    "key_parameters": sec.get("key_parameters", []),
                                    "research_focus": sec.get("research_focus", ""),
                                    # 兼容旧字段名
                                    "name": sec.get("title", f"章节 {i+1}"),
                                }
                                normalized["sections"].append(normalized_section)
                            
                            return normalized
                
                # 纯文本响应，继续迭代
                if result.get("content"):
                    messages.append({"role": "assistant", "content": result["content"]})
                    messages.append({
                        "role": "user",
                        "content": "请调用 Sections 工具输出最终的章节规划。"
                    })
                else:
                    break
                    
            except Exception as e:
                print(f"Center Agent 调用失败: {e}")
                import traceback
                traceback.print_exc()
                return {"error": str(e)}
        
        return {"error": "未能生成有效的章节规划"}


# 全局实例
center_agent = CenterAgent()



