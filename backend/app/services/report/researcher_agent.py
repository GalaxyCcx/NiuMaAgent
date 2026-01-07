"""
Researcher Agent - 章节研究 Agent
负责：执行数据搜索、生成章节内容、调用 Section Processor 处理图表
"""
import json
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

from ...llm import llm_client
from ...models.session import Session
from ..data_executor import data_executor
from ..agent_events import AgentContext, agent_event_manager
from .section_processor import SectionProcessor
from .nl2sql_agent import nl2sql_agent


# Researcher 工具定义 - 与 Researcher-tool-0904-v3.json 保持一致
RESEARCHER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Search",
            "description": "根据用户需求检索单张数据分析报表并定义查询参数。⚠️⚠️⚠️ **参数来源铁律**：所有参数只能来自用户输入或之前Search工具表的返回结果，❌禁止编造参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_description": {
                        "type": "string",
                        "description": "具体分析场景的业务描述"
                    },
                    "table": {
                        "type": "object",
                        "description": "需要查询的单个数据报表",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "系统内注册的报表名称"
                            },
                            "target_fields": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "需要提取的字段列表。❌❌❌ **字段名必须与知识库表定义完全一致** ❌❌❌！"
                            },
                            "filters": {
                                "type": "object",
                                "description": "该报表的查询筛选条件",
                                "additionalProperties": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "number"},
                                        {"type": "boolean"},
                                        {"type": "array", "items": {"type": "string"}}
                                    ]
                                }
                            },
                            "selection_reason": {
                                "type": "string",
                                "description": "选择此报表的具体原因"
                            }
                        },
                        "required": ["table_name", "target_fields"]
                    }
                },
                "required": ["scenario_description", "table"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Section",
            "description": "生成报告章节。【重要】本工具只输出图表渲染需求（purpose + insight_summary），具体的图表配置由专门的图表Agent处理。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "章节名称（⚠️ 必须使用用户输入中的sections[i].title，不要自己编造章节名称）"
                    },
                    "description": {
                        "type": "string",
                        "description": "章节结构描述。格式：【分析目标】一句话说明本章要回答什么问题 | 【分析路径】1.第一步→产出 2.第二步→产出 ... | 【完成标准】需要回答哪些问题才算完成"
                    },
                    "discoveries": {
                        "type": "array",
                        "description": "核心发现列表，每个发现必须包含洞察和图表需求",
                        "items": {
                            "type": "object",
                            "properties": {
                                "discovery_id": {
                                    "type": "string",
                                    "description": "发现编号，格式：discovery_1, discovery_2..."
                                },
                                "title": {
                                    "type": "string",
                                    "description": "发现标题（简短，含关键数值）。discovery_1应定位问题，discovery_2+用【主因】/【次因】等标记"
                                },
                                "insight": {
                                    "type": "string",
                                    "description": "洞察内容。必须包含：1) 导语（核心发现）；2) markdown表格（关键数据，表格前后必须空一行）；3) 承接语（引出图表）。使用{{CHART:chart_id}}占位符引用图表"
                                },
                                "chart_requirements": {
                                    "type": "array",
                                    "description": "图表渲染需求列表。只需描述目的和洞察摘要，❌禁止指定具体字段名/指标名",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "chart_id": {
                                                "type": "string",
                                                "description": "图表唯一标识符，用于占位符引用，如'chart_1'"
                                            },
                                            "purpose": {
                                                "type": "string",
                                                "description": "图表目的：想证明什么观点"
                                            },
                                            "insight_summary": {
                                                "type": "string",
                                                "description": "洞察摘要：这个图表要支撑的核心结论（含关键数值）"
                                            },
                                            "data_ids": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "使用的数据源ID列表（Search返回的dataId）"
                                            }
                                        },
                                        "required": ["chart_id", "purpose", "insight_summary", "data_ids"]
                                    }
                                },
                                "data_interpretation": {
                                    "type": "string",
                                    "description": "数据解读（2-3句，突出关键趋势/极值/拐点）"
                                }
                            },
                            "required": ["discovery_id", "title", "insight", "chart_requirements", "data_interpretation"]
                        },
                        "minItems": 2
                    },
                    "conclusion": {
                        "type": "string",
                        "description": "结论与建议。包含：1) 核心结论（含数值）；2) 基于归因的行动建议；3) 可选：预测建议效果"
                    },
                    "data_references": {
                        "type": "array",
                        "description": "数据引用列表。⚠️⚠️⚠️ 必须填写！列出本section使用的所有search结果的dataId",
                        "items": {
                            "type": "object",
                            "properties": {
                                "data_id": {"type": "string", "description": "Search工具返回的dataId"},
                                "description": {"type": "string", "description": "该数据源的描述"},
                                "usage": {"type": "string", "description": "该数据在本section中的用途"}
                            },
                            "required": ["data_id", "description", "usage"]
                        },
                        "minItems": 1
                    }
                },
                "required": ["name", "description", "discoveries", "conclusion", "data_references"]
            }
        }
    }
]


def load_researcher_prompt(knowledge: str, date: str) -> str:
    """加载 Researcher Agent 系统提示词"""
    prompt_path = Path(__file__).parent.parent.parent.parent.parent / "prompt" / "Researcher-0904-Flexible-v2"
    
    if prompt_path.exists():
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
        
        # 替换占位符
        template = template.replace("{knowledge}", knowledge)
        template = template.replace("{date}", date)
        return template
    
    # 如果文件不存在，使用简化版
    return f"""你是一名研究员，负责完成报告的特定章节。

## 工作流程
Think（内部思考）→ Search（可多次）→ Section

## 规则
- 每次 Search 后评估是否需要继续下钻
- Section 只调用一次，汇总所有 Search 结果
- 标题必须是结论，不是"XX分析"
- insight 必须包含 markdown 表格
- 图表配置由 chart_requirements 描述，由专门的图表 Agent 处理

## 今日日期
{date}

## 数据知识库
{knowledge}
"""


class ResearcherAgent:
    """Researcher Agent - 章节研究"""
    
    def __init__(self):
        self.section_processor = SectionProcessor()
        self.search_results: Dict[str, Dict[str, Any]] = {}  # data_id -> result
    
    async def research_section(
        self,
        session: Session,
        section_definition: Dict[str, Any],
        report_context: Dict[str, Any],  # 新增：全局上下文
        knowledge: str,
        date: str,
        agent_id: str = None,  # 新增：用于事件追踪
    ) -> Dict[str, Any]:
        """
        执行章节研究
        
        Args:
            session: 用户会话
            section_definition: 章节定义（来自 Center Agent）
            report_context: 报告全局上下文（topic, parameters）
            knowledge: 数据知识库上下文
            date: 当前日期
            agent_id: Agent ID（用于事件追踪）
        
        Returns:
            完整的章节数据（包含渲染好的图表配置）
        """
        section_title = section_definition.get('title', section_definition.get('name', 'Unknown'))
        
        # 创建事件上下文
        self.agent_ctx = AgentContext(
            agent_type="research",
            agent_label=f"研究: {section_title[:20]}",
            session_id=session.session_id,
            agent_id=agent_id or agent_event_manager.generate_agent_id("research"),
        )
        
        print(f"\n{'='*60}")
        print(f"开始研究章节: {section_title}")
        print(f"{'='*60}")
        
        # 发射 start 事件
        await self.agent_ctx.emit("start", {"section_title": section_title})
        
        # 加载系统提示词
        system_prompt = load_researcher_prompt(knowledge, date)
        
        # 提取章节详细信息
        research_description = section_definition.get('research_description', '')
        analysis_method = section_definition.get('analysis_method', '')
        key_parameters = section_definition.get('key_parameters', [])
        research_focus = section_definition.get('research_focus', '')
        
        # 构建完整的用户消息（包含全局上下文）
        user_message = f"""请完成以下章节的研究：

## 报告主题
{report_context.get('topic', '数据分析报告')}

## 报告参数
{json.dumps(report_context.get('parameters', {}), ensure_ascii=False, indent=2)}

---

## 本章节信息

### 章节标题
{section_title}

### 详细研究说明（5-7句话描述）
{research_description}

### 分析方法
{analysis_method}

### 必须涵盖的关键参数
{chr(10).join(f"- {param}" for param in key_parameters) if key_parameters else "无特定要求"}

### 研究重点
{research_focus}

---

## 重要要求
1. 每个 discovery 必须包含 markdown 表格
2. discoveries 数量至少 2 个，应覆盖【现状】→【定位】→【主因/次因】
3. 标题必须是结论，不是"XX分析"
4. 所有数据必须来自 Search 查询，禁止编造
5. 调用 Section 时必须填写 data_references

请开始研究，先思考分析方法，然后执行 Search 获取数据，最后调用 Section 输出结果。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # 打印初始 message list
        print(f"\n[Researcher] === 初始 Message List ===")
        print(f"  [0] role=system, content={system_prompt[:100]}...")
        print(f"  [1] role=user, content={user_message[:200]}...")
        print(f"[Researcher] === End Initial Messages ===\n")
        
        max_iterations = 15
        search_count = 0  # 跟踪 Search 调用次数
        
        for iteration in range(max_iterations):
            print(f"\n--- Researcher [{section_title[:25]}] 迭代 {iteration + 1}/{max_iterations} ---")
            print(f"    已完成 {search_count} 次 Search，消息数: {len(messages)}")
            
            # 每次迭代打印完整 message list
            if iteration == 0 or iteration >= 5:  # 第一次和后面几次详细打印
                print(f"\n    [Researcher] === Message List (迭代 {iteration + 1}) ===")
                for i, msg in enumerate(messages):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    content_preview = str(content)[:80].replace('\n', ' ') if content else "(无)"
                    tool_calls = msg.get("tool_calls", [])
                    
                    print(f"      [{i}] role={role}")
                    print(f"          content: {content_preview}...")
                    if tool_calls:
                        for tc in tool_calls:
                            func_name = tc.get('function', {}).get('name', 'unknown')
                            print(f"          tool_call: {func_name}")
                    if role == "tool":
                        tool_call_id = msg.get("tool_call_id", "")
                        print(f"          tool_call_id: {tool_call_id}")
                print(f"    [Researcher] === End Message List ===\n")
            
            try:
                # 如果 Search 次数较多，提示 LLM 应该结束
                if search_count >= 5 and iteration >= 6:
                    messages.append({
                        "role": "user",
                        "content": "你已经收集了足够的数据。请现在调用 Section 工具输出分析结果，不要再执行 Search。"
                    })
                    print(f"    [提示] 数据足够，要求输出 Section")
                
                # 发射请求事件
                await self.agent_ctx.emit_request(messages)
                
                # 定义 chunk 回调
                async def on_chunk(chunk: str, chunk_type: str):
                    await self.agent_ctx.emit_chunk(chunk, chunk_type)
                
                result = await llm_client.chat(
                    messages=messages,
                    agent_name="research",
                    tools=RESEARCHER_TOOLS,
                    stream=False,
                    chunk_callback=on_chunk,  # 流式接收 chunk
                )
                
                # 发射响应事件（完整结果）
                await self.agent_ctx.emit_response(
                    content=result.get("content"),
                    tool_calls=result.get("tool_calls"),
                )
                
                print(f"    LLM 返回: content={bool(result.get('content'))}, tool_calls={bool(result.get('tool_calls'))}")
                
                if result.get("tool_calls"):
                    for tool_call in result["tool_calls"]:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])
                        
                        # 发射工具调用事件
                        await self.agent_ctx.emit_tool_call(tool_name, tool_args)
                        print(f"    调用工具: {tool_name}")
                        
                        if tool_name == "Search":
                            search_count += 1
                            
                            # 如果 Search 次数过多，强制要求输出 Section
                            if search_count > 8:
                                print(f"    [警告] Search 次数过多 ({search_count})，强制要求输出 Section")
                                messages.append({
                                    "role": "assistant",
                                    "content": "我已经收集了足够的数据进行分析。"
                                })
                                messages.append({
                                    "role": "user",
                                    "content": "请直接调用 Section 工具输出分析结果，基于你已收集的数据。"
                                })
                                continue  # 跳过这次 Search，要求输出 Section
                            
                            # 执行 Search
                            tool_result = await self._execute_search(session, tool_args)
                            
                            # 只保存成功的结果（包含 _full_data）
                            if tool_result.get("success") and tool_result.get("data_id"):
                                # 保存时使用 _full_data 或 sample_data
                                saved_result = tool_result.copy()
                                if "_full_data" in saved_result:
                                    saved_result["sample_data"] = saved_result.pop("_full_data")
                                self.search_results[tool_result["data_id"]] = saved_result
                                print(f"    [Search] 成功保存数据: {tool_result['data_id']}, 行数: {tool_result.get('row_count', 0)}")
                            elif not tool_result.get("success"):
                                # Search 失败，记录错误
                                error_msg = tool_result.get("error", "未知错误")
                                print(f"    [Search] 查询失败: {error_msg}")
                            
                            # 构建返回给 LLM 的压缩结果（不包含 _full_data）
                            llm_result = {k: v for k, v in tool_result.items() if not k.startswith("_")}
                            
                            # 如果查询失败，添加重试建议
                            if not tool_result.get("success"):
                                llm_result["retry_suggestion"] = "查询失败，请检查表名和字段名是否正确，或尝试简化查询条件"
                            
                            # 添加到消息历史
                            messages.append({
                                "role": "assistant",
                                "tool_calls": [{
                                    "id": tool_call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": tool_call["function"]["arguments"]
                                    }
                                }]
                            })
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": json.dumps(llm_result, ensure_ascii=False)
                            })
                            
                            # 发射工具结果事件
                            row_count = tool_result.get("row_count", 0)
                            success_status = "成功" if tool_result.get("success") else "失败"
                            await self.agent_ctx.emit_tool_result("Search", f"{success_status}: 返回 {row_count} 条数据")
                            
                            # 打印 message list 变化
                            print(f"    [消息] 添加 assistant tool_call 和 tool response")
                            print(f"    [消息] 当前消息数: {len(messages)}")
                        
                        elif tool_name == "Section":
                            discoveries_count = len(tool_args.get('discoveries', []))
                            print(f"    处理 Section，共 {discoveries_count} 个 discoveries")
                            print(f"    可用 search_results: {len(self.search_results)} 个")
                            
                            # 检查是否有有效数据
                            if not self.search_results:
                                print(f"    [警告] 没有有效的 search_results，章节可能为空")
                                # 添加错误提示，让 LLM 知道需要先获取数据
                                messages.append({
                                    "role": "assistant",
                                    "tool_calls": [{
                                        "id": tool_call["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": tool_call["function"]["arguments"]
                                        }
                                    }]
                                })
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call["id"],
                                    "content": json.dumps({
                                        "error": "没有可用的数据，请先执行 Search 获取数据后再调用 Section",
                                        "suggestion": "请检查之前的 Search 是否成功，或尝试使用不同的查询参数"
                                    }, ensure_ascii=False)
                                })
                                messages.append({
                                    "role": "user",
                                    "content": "Section 需要数据支撑，但之前的 Search 都没有返回有效数据。请重新执行 Search，使用更简单的查询条件（如减少 filters，或使用 SELECT *），确保能获取到数据后再调用 Section。"
                                })
                                continue  # 继续迭代，让 LLM 重新 Search
                            
                            # 检查 discoveries 是否为空
                            if discoveries_count == 0:
                                print(f"    [警告] discoveries 为空，要求 LLM 补充")
                                messages.append({
                                    "role": "assistant",
                                    "tool_calls": [{
                                        "id": tool_call["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": tool_call["function"]["arguments"]
                                        }
                                    }]
                                })
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call["id"],
                                    "content": json.dumps({
                                        "error": "Section 的 discoveries 不能为空，至少需要 2 个发现",
                                        "suggestion": "请基于已获取的数据，生成至少 2 个有意义的发现"
                                    }, ensure_ascii=False)
                                })
                                continue
                            
                            section = await self.section_processor.process(
                                section_params=tool_args,
                                search_results=self.search_results,
                                session_id=session.session_id,  # 传入 session_id 用于事件追踪
                            )
                            
                            # 添加章节ID
                            section["section_id"] = section_definition.get("section_id", str(uuid.uuid4()))
                            
                            # 验证 section 是否有内容
                            if not section.get("discoveries"):
                                print(f"    [警告] 生成的 section 没有 discoveries")
                                section["discoveries"] = [{
                                    "discovery_id": "fallback_1",
                                    "title": "数据分析概述",
                                    "insight": "由于数据获取或处理过程中遇到问题，本章节内容生成不完整。",
                                    "charts": []
                                }]
                            
                            print(f"    [完成] 章节处理完成: {section.get('name', 'Unknown')}, discoveries: {len(section.get('discoveries', []))}")
                            
                            # 发射 complete 事件
                            await self.agent_ctx.emit("complete", {
                                "section_name": section.get('name', 'Unknown'),
                                "discoveries_count": len(section.get('discoveries', [])),
                            })
                            
                            return {
                                "section": section,
                                "search_results": self.search_results,
                            }
                
                else:
                    # 纯文本响应（思考过程）
                    if result.get("content"):
                        content_preview = result['content'][:150].replace('\n', ' ')
                        print(f"    思考: {content_preview}...")
                        messages.append({"role": "assistant", "content": result["content"]})
                        
                        # 引导 LLM 继续执行工具调用
                        if search_count == 0:
                            messages.append({
                                "role": "user",
                                "content": "请开始执行 Search 获取数据。"
                            })
                        elif search_count >= 3:
                            messages.append({
                                "role": "user",
                                "content": "你已经有足够的数据了。请调用 Section 工具输出分析结果。"
                            })
                    else:
                        print(f"    [警告] 空响应")
                    
            except Exception as e:
                print(f"    [错误] 迭代 {iteration + 1} 失败: {e}")
                import traceback
                traceback.print_exc()
                
                # 添加错误信息让模型知道
                messages.append({
                    "role": "user",
                    "content": f"上一步执行出错: {str(e)}。请调整后重试。"
                })
        
        # 达到最大迭代次数，尝试基于已有数据生成基本内容
        print(f"    [警告] 达到最大迭代次数，尝试生成基本章节内容")
        print(f"    已收集的数据: {len(self.search_results)} 个 search_results")
        
        section_name = section_definition.get("title", section_definition.get("name", "数据分析"))
        
        # 如果有数据，生成一个基本的 discovery
        fallback_discoveries = []
        if self.search_results:
            # 汇总已收集的数据
            data_summary_parts = []
            for data_id, result in self.search_results.items():
                row_count = result.get("row_count", 0)
                table_name = result.get("table_name", "未知表")
                summary = result.get("summary", "")
                data_summary_parts.append(f"- {table_name}: {row_count} 条数据")
                if summary:
                    data_summary_parts.append(f"  摘要: {summary}")
            
            data_summary = "\n".join(data_summary_parts) if data_summary_parts else "暂无数据摘要"
            
            fallback_discoveries.append({
                "discovery_id": "fallback_1",
                "title": f"【数据概览】{section_name}",
                "insight": f"""本章节的数据分析过程中遇到了一些问题，以下是已收集到的数据概况：

{data_summary}

由于分析流程未能完成，具体的深入分析和可视化图表暂时无法生成。建议重新运行分析或检查数据质量。""",
                "charts": [],
                "data_interpretation": "数据已收集但分析流程未完成"
            })
        else:
            fallback_discoveries.append({
                "discovery_id": "fallback_1",
                "title": f"【待分析】{section_name}",
                "insight": "本章节的数据获取过程中遇到问题，未能成功获取分析所需的数据。可能的原因包括：\n\n- 数据表名或字段名不匹配\n- 查询条件过于严格\n- 数据源暂时不可用\n\n建议检查数据配置后重新尝试。",
                "charts": [],
                "data_interpretation": "数据获取失败"
            })
        
        # 发射 complete 事件（即使是降级内容）
        await self.agent_ctx.emit("complete", {
            "section_name": section_name,
            "discoveries_count": len(fallback_discoveries),
            "fallback": True,
        })
        
        return {
            "section": {
                "section_id": section_definition.get("section_id", str(uuid.uuid4())),
                "name": section_name,
                "discoveries": fallback_discoveries,
                "conclusion": "由于分析过程中遇到问题，本章节内容为降级版本。建议检查数据源和查询条件后重新生成。",
                "error": "达到最大迭代次数"
            },
            "search_results": self.search_results,
        }
    
    async def _execute_search(
        self,
        session: Session,
        search_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行 Search 工具调用
        
        Args:
            session: 用户会话
            search_params: Search 参数（新格式：包含 scenario_description 和 table）
        
        Returns:
            搜索结果（压缩格式）
        """
        # 兼容新旧格式
        scenario_description = search_params.get("scenario_description", "")
        table_info = search_params.get("table", {})
        
        # 从 table 对象中提取参数，如果不存在则尝试从顶层获取（兼容旧格式）
        table_name = table_info.get("table_name", search_params.get("table_name", ""))
        target_fields = table_info.get("target_fields", search_params.get("target_fields", []))
        filters = table_info.get("filters", search_params.get("conditions", {}))
        selection_reason = table_info.get("selection_reason", "")
        
        purpose = scenario_description or search_params.get("purpose", "")
        limit = 500  # 查询更多数据用于分析
        
        print(f"    Search: {table_name}")
        print(f"      目的: {purpose[:60]}...")
        print(f"      字段: {target_fields[:5]}...")
        print(f"      过滤: {filters}")
        
        # 智能重试机制（最多重试 3 次）
        max_retries = 3
        retry_hint = ""
        last_error = ""
        last_sql = ""
        
        for attempt in range(max_retries + 1):
            sql = await self._generate_sql_with_nl2sql(
                session=session,
                table_name=table_name,
                target_fields=target_fields,
                filters=filters,
                purpose=purpose + retry_hint,
                limit=limit,
            )
            
            print(f"    SQL (尝试 {attempt + 1}/{max_retries + 1}): {sql[:120]}...")
            last_sql = sql
            
            # 执行查询
            success, result, message = data_executor.execute_sql(session, sql, max_rows=limit)
            
            if success and result.get("data"):
                # 验证结果是否符合需求
                is_valid, issues, suggestions = nl2sql_agent.validate_result(
                    query_intent=purpose,
                    result_columns=result.get("columns", []),
                    result_data=result.get("data", []),
                )
                
                if is_valid:
                    print(f"    ✅ 验证通过")
                    break
                else:
                    print(f"    ⚠️ 验证失败: {issues}")
                    if attempt < max_retries:
                        # 构建重试提示
                        retry_hint = f"\n\n【上次 SQL 问题】{issues}\n【建议】" + "; ".join(suggestions)
                        print(f"    重试中...")
                    else:
                        print(f"    已达最大重试次数，使用当前结果")
            elif not success:
                # SQL 执行失败，提取修复建议并重试
                last_error = message
                print(f"    ❌ SQL 执行失败: {message[:100]}...")
                
                if attempt < max_retries:
                    # 从 result 中提取修复建议
                    fix_suggestion = ""
                    if isinstance(result, dict):
                        fix_suggestion = result.get("fix_suggestion", "") or result.get("validation_error", "")
                    
                    # 构建重试提示，包含错误信息和修复建议
                    retry_hint = f"""

【上次 SQL 执行失败】
错误: {message[:200]}
失败的 SQL: {sql[:200]}
"""
                    if fix_suggestion:
                        retry_hint += f"修复建议: {fix_suggestion}\n"
                    
                    retry_hint += """
【重要】请生成更简单的 SQL：
1. 不要使用嵌套子查询
2. 不要使用 UNION/INTERSECT
3. 特殊字符字段名用反引号包裹
4. 以数字开头的别名用反引号包裹
5. 尽量只用 SELECT + WHERE + GROUP BY + ORDER BY
"""
                    print(f"    重试中（第 {attempt + 2} 次）...")
                else:
                    print(f"    已达最大重试次数")
            else:
                # success=True 但没有数据，可能是查询条件太严格
                print(f"    ⚠️ 查询成功但无数据，可能条件太严格")
                if attempt < max_retries:
                    retry_hint = f"""

【上次查询返回空结果】
可能原因: 筛选条件太严格
建议: 放宽 WHERE 条件，或移除部分筛选条件
"""
                    print(f"    重试中...")
                else:
                    break
        
        data_id = str(uuid.uuid4())
        
        if success:
            data = result.get("data", [])
            total_count = result.get("total_count", len(data))
            
            # 提取关键指标
            key_metrics = self._extract_key_metrics(data, target_fields)
            
            # 智能压缩数据（返回给 LLM 的精简版本）
            compressed = self._smart_compress_data(data, target_fields, purpose)
            
            # 生成数据摘要
            summary = self._generate_data_summary(data, target_fields, key_metrics, total_count)
            
            print(f"    结果: {len(data)} 行")
            print(f"    压缩策略: {compressed['strategy']}")
            print(f"    摘要: {summary[:100]}...")
            
            return {
                "data_id": data_id,
                "success": True,
                "purpose": purpose,
                "table_name": table_name,
                # 压缩后的数据返回给 LLM
                "summary": summary,
                "key_metrics": key_metrics,
                "compressed_data": compressed["data"],  # 压缩后的数据
                "compression_strategy": compressed["strategy"],
                "sample_data": compressed["sample"],  # 代表性样本
                "row_count": len(data),
                "total_count": total_count,
                "columns": result.get("columns", []),
                # 保留完整数据用于图表渲染（不发给 LLM）
                "_full_data": data,  # 保留全部数据
            }
        else:
            print(f"    查询失败: {message}")
            return {
                "data_id": data_id,
                "success": False,
                "error": message,
                "purpose": purpose,
            }
    
    def _generate_data_summary(
        self,
        data: List[Dict[str, Any]],
        fields: List[str],
        metrics: Dict[str, Any],
        total_count: int,
    ) -> str:
        """生成数据摘要（一句话总结）"""
        if not data:
            return "查询未返回数据"
        
        summary_parts = [f"查询返回 {len(data)} 条数据（共 {total_count} 条）"]
        
        # 添加关键指标
        for field in fields[:3]:
            if f"{field}_max" in metrics:
                max_val = metrics[f"{field}_max"]
                avg_val = metrics.get(f"{field}_avg", 0)
                summary_parts.append(f"{field}最大值={max_val:.2f}，平均值={avg_val:.2f}")
        
        return "；".join(summary_parts)
    
    async def _generate_sql_with_nl2sql(
        self,
        session: Session,
        table_name: str,
        target_fields: List[str],
        filters: Dict[str, Any],
        purpose: str,
        limit: int = 500,
    ) -> str:
        """
        使用 NL2SQL Agent 生成 SQL，失败则回退到简单拼接
        """
        # 尝试使用 NL2SQL（对于复杂查询）
        if purpose and len(purpose) > 20:
            try:
                # 获取表结构信息
                table_schemas = self._get_table_schemas(session, table_name)
                
                if table_schemas:
                    # 构建查询意图 - 增强版，明确分析需求
                    query_intent = f"""分析需求: {purpose}

请注意以下规则:
- 如果需求涉及"占比"、"比例"、"百分比"，必须在 SQL 中计算百分比值
- 如果需求涉及"趋势"、"变化"、"增长"，必须按时间维度 GROUP BY 并计算聚合指标
- 如果需求涉及"分布"、"分类统计"，必须 GROUP BY 相应维度
- 结果字段必须使用中文别名，便于图表展示（如 AS 年份, AS 游戏数量, AS 占比）
- 不要只返回原始数据，要返回可直接用于图表展示的聚合结果"""
                    
                    if filters:
                        filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items())
                        query_intent += f"\n\n筛选条件：{filter_desc}"
                    if target_fields:
                        query_intent += f"\n参考字段：{', '.join(target_fields[:10])}"
                    
                    # 调用 NL2SQL Agent
                    result = await nl2sql_agent.generate_sql(
                        query_intent=query_intent,
                        table_schemas=table_schemas,
                        session_id=session.session_id,  # 传入 session_id 用于事件追踪
                    )
                    
                    if result.get("success") and result.get("sql"):
                        print(f"    [NL2SQL] 使用 AI 生成的 SQL")
                        return result["sql"]
                    else:
                        print(f"    [NL2SQL] 生成失败，回退到简单拼接: {result.get('error', 'unknown')}")
            except Exception as e:
                print(f"    [NL2SQL] 异常，回退到简单拼接: {e}")
        
        # 回退：简单 SQL 拼接
        fields_str = ", ".join(f"`{f}`" for f in target_fields) if target_fields else "*"
        sql = f"SELECT {fields_str} FROM `{table_name}`"
        
        # 添加条件
        if filters:
            where_parts = []
            for field, value in filters.items():
                if isinstance(value, str):
                    where_parts.append(f"`{field}` = '{value}'")
                elif isinstance(value, list):
                    values_str = ", ".join(f"'{v}'" for v in value)
                    where_parts.append(f"`{field}` IN ({values_str})")
                else:
                    where_parts.append(f"`{field}` = {value}")
            if where_parts:
                sql += " WHERE " + " AND ".join(where_parts)
        
        sql += f" LIMIT {limit}"
        return sql
    
    def _get_table_schemas(self, session: Session, table_name: str) -> List[Dict[str, Any]]:
        """获取表结构信息"""
        schemas = []
        
        if session.tables:
            for table in session.tables:
                if table.table_name == table_name or not table_name:
                    schema = {
                        "table_name": table.table_name,
                        "row_count": table.row_count,
                        "columns": []
                    }
                    
                    for col in table.columns:
                        # 注意：col 是字典，不是 Pydantic 模型
                        schema["columns"].append({
                            "name": col.get("name", col.get("column_name", "")),
                            "type": col.get("dtype", col.get("type", "unknown")),
                            "sample": str(col.get("sample_values", col.get("sample", "")))[:50],
                        })
                    
                    schemas.append(schema)
                    
                    # 如果指定了表名，只返回该表
                    if table_name:
                        break
        
        return schemas
    
    def _smart_compress_data(
        self,
        data: List[Dict[str, Any]],
        fields: List[str],
        purpose: str,
    ) -> Dict[str, Any]:
        """
        智能压缩数据，根据数据特征选择最佳压缩策略
        
        策略：
        1. 完整数据：数据量 < 20 行，不压缩
        2. Top-N：适用于排序/排名分析
        3. 分组聚合：适用于分类统计
        4. 等间隔采样：适用于趋势分析
        5. 统计摘要：数据量大时使用
        """
        if not data:
            return {"strategy": "empty", "data": [], "sample": []}
        
        row_count = len(data)
        
        # 策略1：数据量小，直接返回全部
        if row_count <= 20:
            return {
                "strategy": "complete",
                "data": data,
                "sample": data[:5],
            }
        
        # 分析目的关键词
        purpose_lower = purpose.lower()
        
        # 策略2：Top-N（排名/最高/最低）
        if any(kw in purpose_lower for kw in ["top", "排名", "最高", "最低", "前", "排行"]):
            # 找到数值字段进行排序
            numeric_field = self._find_primary_numeric_field(data, fields)
            if numeric_field:
                sorted_data = sorted(data, key=lambda x: float(x.get(numeric_field, 0) or 0), reverse=True)
                top_n = sorted_data[:10]  # Top 10
                bottom_n = sorted_data[-5:] if row_count > 15 else []  # Bottom 5
                return {
                    "strategy": "top_n",
                    "data": {
                        "top_10": top_n,
                        "bottom_5": bottom_n,
                        "total_count": row_count,
                    },
                    "sample": top_n[:5],
                }
        
        # 策略3：分组聚合（分类/分布/占比）
        if any(kw in purpose_lower for kw in ["分类", "分布", "类型", "占比", "按", "各"]):
            category_field = self._find_category_field(data, fields)
            if category_field:
                aggregated = self._aggregate_by_category(data, category_field, fields)
                return {
                    "strategy": "grouped",
                    "data": aggregated,
                    "sample": data[:5],
                }
        
        # 策略4：等间隔采样（趋势/变化/年度/月度）
        if any(kw in purpose_lower for kw in ["趋势", "变化", "年", "月", "时间", "历史"]):
            sample_count = min(15, row_count)
            step = max(1, row_count // sample_count)
            sampled = [data[i] for i in range(0, row_count, step)][:sample_count]
            return {
                "strategy": "sampled",
                "data": sampled,
                "sample": sampled[:5],
            }
        
        # 策略5：默认统计摘要 + 采样
        sample_count = min(10, row_count)
        step = max(1, row_count // sample_count)
        sampled = [data[i] for i in range(0, row_count, step)][:sample_count]
        
        return {
            "strategy": "summary_with_sample",
            "data": {
                "sample": sampled,
                "total_count": row_count,
                "first_row": data[0] if data else None,
                "last_row": data[-1] if data else None,
            },
            "sample": sampled[:5],
        }
    
    def _find_primary_numeric_field(self, data: List[Dict], fields: List[str]) -> Optional[str]:
        """找到主要的数值字段"""
        if not data:
            return None
        
        for field in fields:
            values = [row.get(field) for row in data[:10] if row.get(field) is not None]
            if values:
                try:
                    [float(v) for v in values]
                    return field
                except (TypeError, ValueError):
                    continue
        return None
    
    def _find_category_field(self, data: List[Dict], fields: List[str]) -> Optional[str]:
        """找到分类字段（非数值、有限取值）"""
        if not data:
            return None
        
        for field in fields:
            values = [row.get(field) for row in data if row.get(field) is not None]
            if not values:
                continue
            
            # 检查是否为字符串类型
            if isinstance(values[0], str):
                unique_count = len(set(values))
                # 取值数量在 2-50 之间的视为分类字段
                if 2 <= unique_count <= 50:
                    return field
        return None
    
    def _aggregate_by_category(
        self, 
        data: List[Dict], 
        category_field: str, 
        fields: List[str]
    ) -> Dict[str, Any]:
        """按分类字段聚合"""
        from collections import defaultdict
        
        groups = defaultdict(list)
        for row in data:
            key = row.get(category_field, "其他")
            groups[key].append(row)
        
        result = []
        for category, rows in sorted(groups.items(), key=lambda x: -len(x[1]))[:15]:
            agg = {"category": category, "count": len(rows)}
            
            # 对数值字段计算平均值
            for field in fields:
                if field == category_field:
                    continue
                values = []
                for row in rows:
                    try:
                        values.append(float(row.get(field, 0) or 0))
                    except:
                        pass
                if values:
                    agg[f"{field}_avg"] = sum(values) / len(values)
                    agg[f"{field}_sum"] = sum(values)
            
            result.append(agg)
        
        return {
            "grouped_by": category_field,
            "groups": result,
            "total_groups": len(groups),
        }
    
    def _extract_key_metrics(
        self,
        data: List[Dict[str, Any]],
        fields: List[str],
    ) -> Dict[str, Any]:
        """提取关键指标"""
        if not data:
            return {}
        
        metrics = {
            "record_count": len(data),
        }
        
        # 对数值字段计算统计
        for field in fields:
            values = [row.get(field) for row in data if row.get(field) is not None]
            
            # 检查是否为数值
            numeric_values = []
            for v in values:
                try:
                    numeric_values.append(float(v))
                except (TypeError, ValueError):
                    continue
            
            if numeric_values:
                metrics[f"{field}_sum"] = sum(numeric_values)
                metrics[f"{field}_avg"] = sum(numeric_values) / len(numeric_values)
                metrics[f"{field}_max"] = max(numeric_values)
                metrics[f"{field}_min"] = min(numeric_values)
        
        return metrics


