"""
Summary Agent - 报告引言和总结生成
负责：生成报告引言、总结与建议
"""
import json
from typing import Dict, List, Any, Optional

from ...llm import llm_client
from ..agent_events import AgentContext, agent_event_manager


class SummaryAgent:
    """
    Summary Agent - 生成报告的引言和总结
    
    在所有章节研究完成后调用，根据：
    1. 用户原始需求（Clarification 确认的内容）
    2. 报告主题和参数
    3. 各章节的结论
    
    生成：
    1. 引言/摘要：报告的开篇，介绍背景和目标
    2. 总结与建议：综合各章节发现，给出结论和建议
    """
    
    def __init__(self):
        self.system_prompt = """你是一位专业的数据分析报告撰写专家。你的任务是为数据分析报告撰写引言和总结。

## 引言要求（Markdown格式）
引言应该包含以下结构，使用 Markdown 格式输出：

```markdown
本报告基于[数据来源]，针对[分析目标]进行深入分析。

### 研究背景
[2-3句话说明背景和重要性]

### 分析目标
[明确本报告要回答的核心问题，用列表形式]

### 报告结构
本报告共分为X个章节：
1. **章节1名称**：简述内容
2. **章节2名称**：简述内容
...
```

引言长度：200-400字，结构清晰

## 总结与建议要求（Markdown格式）
总结应该使用 Markdown 格式，结构如下：

```markdown
### 📊 核心发现

通过对数据的深入分析，我们发现：

1. **发现1标题**：具体描述
2. **发现2标题**：具体描述
3. **发现3标题**：具体描述

### 💡 关键洞察

[1-2段话总结核心结论]

### 🎯 行动建议

基于以上分析，我们建议：

| 建议 | 说明 | 优先级 |
|-----|------|-------|
| 建议1 | 具体说明 | 高/中/低 |
| 建议2 | 具体说明 | 高/中/低 |

### 📝 局限与展望

[简述分析局限性和未来可深入方向]
```

总结长度：300-500字，使用表格、列表等增强可读性

## ⚠️ Markdown 格式铁律

**表格格式要求**（不遵守会导致渲染失败）：
1. 表格前必须有一个空行
2. 表格后必须有一个空行
3. 不能在句号后直接跟表格，必须先换行再空行

正确示例：
```
这是一段文字。

| 列1 | 列2 |
|-----|-----|
| 值1 | 值2 |

这是后续文字。
```

## 输出格式
请调用 GenerateSummary 工具输出结果，内容必须是完整的 Markdown 格式。"""
    
    async def generate_summary(
        self,
        user_request: str,
        topic: str,
        parameters: Dict[str, Any],
        sections_conclusions: List[Dict[str, Any]],
        clarification_content: Optional[str] = None,
        session_id: str = None,  # 新增：用于事件追踪
    ) -> Dict[str, str]:
        """
        生成报告的引言和总结
        
        Args:
            user_request: 用户原始需求
            topic: 报告主题
            parameters: 报告参数
            sections_conclusions: 各章节的结论列表 [{"name": "章节名", "conclusion": "结论"}]
            clarification_content: Clarification 确认后的需求内容
            session_id: 会话 ID（用于事件追踪）
        
        Returns:
            {"introduction": "引言内容", "summary_and_recommendations": "总结与建议"}
        """
        # 创建事件上下文
        agent_ctx = None
        if session_id:
            agent_ctx = AgentContext(
                agent_type="summary",
                agent_label="Summary: 引言与总结",
                session_id=session_id,
            )
            await agent_ctx.emit("start", {"topic": topic})
        # 构建章节结论摘要
        conclusions_text = ""
        for i, sec in enumerate(sections_conclusions, 1):
            conclusions_text += f"\n### 章节 {i}: {sec.get('name', f'第{i}章')}\n"
            conclusions_text += f"{sec.get('conclusion', '暂无结论')}\n"
        
        # 构建用户消息
        user_message = f"""请为以下数据分析报告撰写引言和总结。

## 用户需求
{clarification_content or user_request}

## 报告主题
{topic}

## 报告参数
{json.dumps(parameters, ensure_ascii=False, indent=2)}

## 各章节结论
{conclusions_text}

请根据以上信息，调用 GenerateSummary 工具生成引言和总结与建议。
注意：总结与建议需要紧密围绕用户的原始需求，给出针对性的建议。"""

        # 工具定义
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "GenerateSummary",
                    "description": "生成报告的引言和总结与建议",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "introduction": {
                                "type": "string",
                                "description": "报告引言（200-400字），包含研究背景、分析目标、数据概述、报告结构"
                            },
                            "summary_and_recommendations": {
                                "type": "string",
                                "description": "总结与建议（300-500字），包含核心发现、关键洞察、行动建议、局限与展望"
                            }
                        },
                        "required": ["introduction", "summary_and_recommendations"]
                    }
                }
            }
        ]
        
        try:
            print(f"[SummaryAgent] 开始生成引言和总结...")
            print(f"  主题: {topic}")
            print(f"  章节数: {len(sections_conclusions)}")
            
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            # 发射请求事件
            if agent_ctx:
                await agent_ctx.emit_request(messages)
            
            # 定义 chunk 回调
            async def on_chunk(chunk: str, chunk_type: str):
                if agent_ctx:
                    await agent_ctx.emit_chunk(chunk, chunk_type)
            
            result = await llm_client.chat(
                messages=messages,
                agent_name="summary",
                tools=tools,
                stream=False,
                chunk_callback=on_chunk if agent_ctx else None,
            )
            
            # 发射响应事件
            if agent_ctx:
                await agent_ctx.emit_response(
                    content=result.get("content"),
                    tool_calls=result.get("tool_calls"),
                )
            
            if result.get("tool_calls"):
                tool_call = result["tool_calls"][0]
                if tool_call["function"]["name"] == "GenerateSummary":
                    args = json.loads(tool_call["function"]["arguments"])
                    
                    introduction = args.get("introduction", "")
                    summary = args.get("summary_and_recommendations", "")
                    
                    print(f"[SummaryAgent] 生成完成:")
                    print(f"  引言长度: {len(introduction)} 字")
                    print(f"  总结长度: {len(summary)} 字")
                    
                    # 发射完成事件
                    if agent_ctx:
                        await agent_ctx.emit("complete", {
                            "intro_length": len(introduction),
                            "summary_length": len(summary),
                        })
                    
                    return {
                        "introduction": introduction,
                        "summary_and_recommendations": summary
                    }
            
            # 如果没有工具调用，尝试从文本中提取
            content = result.get("content", "")
            if content:
                print(f"[SummaryAgent] 警告: 未使用工具调用，使用文本响应")
                if agent_ctx:
                    await agent_ctx.emit("complete", {"fallback": True})
                return {
                    "introduction": "本报告基于用户需求进行数据分析，以下为详细分析结果。",
                    "summary_and_recommendations": content[:500] if len(content) > 500 else content
                }
            
            if agent_ctx:
                await agent_ctx.emit("error", {"message": "未生成有效内容"})
            return {
                "introduction": "",
                "summary_and_recommendations": ""
            }
            
        except Exception as e:
            print(f"[SummaryAgent] 生成失败: {e}")
            import traceback
            traceback.print_exc()
            if agent_ctx:
                await agent_ctx.emit("error", {"message": str(e)})
            return {
                "introduction": "",
                "summary_and_recommendations": ""
            }


# 全局实例
summary_agent = SummaryAgent()

