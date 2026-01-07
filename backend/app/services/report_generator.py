"""
报告生成服务
基于对话内容和数据分析生成结构化报告
"""
import json
from typing import Dict, List, Any, Optional, AsyncGenerator
from datetime import datetime

from ..llm import llm_client
from ..models.session import Session, session_manager
from ..models.report import Report, ReportSection, ChartConfig, report_manager
from .chart_agent import chart_agent
from .data_executor import data_executor


REPORT_OUTLINE_PROMPT = """你是一个数据分析报告专家。根据用户的分析需求和数据信息，生成报告大纲。

**数据信息**:
{data_context}

**用户需求**:
{user_request}

请生成一份专业的数据分析报告大纲，包含以下内容（JSON格式）：

```json
{{
    "title": "报告标题",
    "summary": "报告摘要（100字以内）",
    "sections": [
        {{
            "title": "章节标题",
            "description": "章节内容描述",
            "analysis_type": "overview|trend|distribution|comparison|correlation",
            "suggested_sql": "建议的SQL查询（如果需要）"
        }}
    ]
}}
```

要求：
1. 报告结构清晰，逻辑连贯
2. 每个章节有明确的分析目的
3. 建议的 SQL 要可执行
4. 章节数量适中（3-6个）

只输出 JSON，不要其他内容。
"""


SECTION_CONTENT_PROMPT = """你是一个数据分析专家。请根据以下信息撰写报告章节内容。

**章节标题**: {section_title}
**章节目的**: {section_description}

**查询结果**:
```json
{query_result}
```

请用 Markdown 格式撰写这个章节的内容，包括：
1. 关键发现（用列表形式）
2. 数据解读（1-2段话）
3. 建议或结论（如果适用）

要求：
- 基于实际数据，不要编造
- 语言专业但易懂
- 突出重点数据
- 适当使用 Markdown 格式（标题、列表、粗体等）
"""


class ReportGenerator:
    """报告生成器"""
    
    def generate_report(
        self,
        session: Session,
        user_request: str,
        stream: bool = False,
    ):
        """
        生成报告
        
        Args:
            session: 会话
            user_request: 用户的报告需求描述
            stream: 是否流式返回生成过程
            
        Returns:
            如果 stream=True，返回 AsyncGenerator
            如果 stream=False，返回 awaitable Report
        """
        if stream:
            return self._generate_report_stream(session, user_request)
        else:
            return self._generate_report_sync(session, user_request)
    
    async def _generate_report_stream(
        self,
        session: Session,
        user_request: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式生成报告"""
        
        # 1. 创建报告
        yield {"type": "status", "message": "正在创建报告..."}
        report = report_manager.create_report(
            session_id=session.session_id,
            title="数据分析报告",
        )
        report.source_questions.append(user_request)
        report.status = "generating"
        report_manager.save_report(report)
        
        yield {"type": "report_created", "report_id": report.report_id}
        
        # 2. 生成报告大纲
        yield {"type": "status", "message": "正在生成报告大纲..."}
        
        data_context = self._build_data_context(session)
        outline = await self._generate_outline(data_context, user_request)
        
        if "error" in outline:
            yield {"type": "error", "message": outline["error"]}
            report.status = "error"
            report_manager.save_report(report)
            return
        
        report.title = outline.get("title", "数据分析报告")
        report.summary = outline.get("summary", "")
        report_manager.save_report(report)
        
        yield {"type": "outline", "data": outline}
        
        # 3. 逐章节生成内容
        sections_outline = outline.get("sections", [])
        total_sections = len(sections_outline)
        
        for idx, section_outline in enumerate(sections_outline):
            section_title = section_outline.get("title", f"章节 {idx + 1}")
            
            yield {
                "type": "section_start",
                "index": idx,
                "total": total_sections,
                "title": section_title,
            }
            
            # 执行 SQL 获取数据
            query_result = None
            sql = section_outline.get("suggested_sql")
            
            if sql and sql.strip():
                yield {"type": "status", "message": f"正在执行查询: {section_title}"}
                success, data, message = data_executor.execute_sql(session, sql)
                if success:
                    query_result = data
                    yield {"type": "sql_executed", "sql": sql, "row_count": data.get("row_count", 0)}
            
            # 生成章节内容
            yield {"type": "status", "message": f"正在撰写: {section_title}"}
            
            section_content = await self._generate_section_content(
                section_title=section_title,
                section_description=section_outline.get("description", ""),
                query_result=query_result,
            )
            
            # 生成图表
            charts = []
            if query_result and query_result.get("data"):
                chart_config = await chart_agent.generate_chart_config(
                    purpose=section_outline.get("description", section_title),
                    sample_data=query_result["data"],
                    session_id=session.session_id,
                )
                if "error" not in chart_config:
                    charts.append(ChartConfig(
                        chart_type=chart_config.get("chart_type", "bar"),
                        title=chart_config.get("title", section_title),
                        data_sources=chart_config.get("data_sources", []),
                        rendered_data=query_result["data"],
                    ))
            
            # 创建章节
            section = ReportSection(
                title=section_title,
                content=section_content,
                charts=charts,
                tables=[query_result] if query_result else [],
                order=idx,
            )
            
            report.sections.append(section)
            report_manager.save_report(report)
            
            yield {
                "type": "section_complete",
                "index": idx,
                "section": section.model_dump(),
            }
        
        # 4. 完成
        report.status = "completed"
        report_manager.save_report(report)
        
        yield {"type": "complete", "report": report.model_dump()}
    
    async def _generate_report_sync(
        self,
        session: Session,
        user_request: str,
    ) -> Report:
        """同步生成报告"""
        
        report = report_manager.create_report(
            session_id=session.session_id,
            title="数据分析报告",
        )
        report.source_questions.append(user_request)
        report.status = "generating"
        
        data_context = self._build_data_context(session)
        outline = await self._generate_outline(data_context, user_request)
        
        if "error" in outline:
            report.status = "error"
            report_manager.save_report(report)
            return report
        
        report.title = outline.get("title", "数据分析报告")
        report.summary = outline.get("summary", "")
        
        for idx, section_outline in enumerate(outline.get("sections", [])):
            section_title = section_outline.get("title", f"章节 {idx + 1}")
            
            # 执行 SQL
            query_result = None
            sql = section_outline.get("suggested_sql")
            if sql and sql.strip():
                success, data, message = data_executor.execute_sql(session, sql)
                if success:
                    query_result = data
            
            # 生成内容
            content = await self._generate_section_content(
                section_title=section_title,
                section_description=section_outline.get("description", ""),
                query_result=query_result,
            )
            
            # 生成图表
            charts = []
            if query_result and query_result.get("data"):
                chart_config = await chart_agent.generate_chart_config(
                    purpose=section_outline.get("description", section_title),
                    sample_data=query_result["data"],
                    session_id=session.session_id,
                )
                if "error" not in chart_config:
                    charts.append(ChartConfig(
                        chart_type=chart_config.get("chart_type", "bar"),
                        title=chart_config.get("title", section_title),
                        data_sources=chart_config.get("data_sources", []),
                        rendered_data=query_result["data"],
                    ))
            
            section = ReportSection(
                title=section_title,
                content=content,
                charts=charts,
                tables=[query_result] if query_result else [],
                order=idx,
            )
            report.sections.append(section)
        
        report.status = "completed"
        report_manager.save_report(report)
        return report
    
    def _build_data_context(self, session: Session) -> str:
        """构建数据上下文"""
        if not session.tables:
            return "暂无数据"
        
        context_parts = []
        for table in session.tables:
            # 获取表描述
            table_desc = "无"
            if table.table_description:
                table_desc = table.table_description.get("description", "无") if isinstance(table.table_description, dict) else "无"
            
            table_info = f"**表名**: {table.table_name}\n"
            table_info += f"**行数**: {table.row_count}\n"
            table_info += f"**描述**: {table_desc}\n"
            table_info += "**字段**:\n"
            
            for col in table.columns[:20]:
                col_desc = col.get("description", col.get("semantic_type", ""))
                table_info += f"- {col['name']} ({col.get('semantic_type', 'text')}): {col_desc}\n"
            
            context_parts.append(table_info)
        
        return "\n\n".join(context_parts)
    
    async def _generate_outline(
        self,
        data_context: str,
        user_request: str,
    ) -> Dict[str, Any]:
        """生成报告大纲"""
        
        prompt = REPORT_OUTLINE_PROMPT.format(
            data_context=data_context,
            user_request=user_request,
        )
        
        try:
            result = await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                agent_name="research",
                stream=False,
            )
            
            content = result.get("content", "").strip()
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content.strip())
            
        except Exception as e:
            print(f"生成报告大纲失败: {e}")
            return {"error": str(e)}
    
    async def _generate_section_content(
        self,
        section_title: str,
        section_description: str,
        query_result: Optional[Dict[str, Any]],
    ) -> str:
        """生成章节内容"""
        
        if query_result:
            result_str = json.dumps(
                query_result.get("data", [])[:20],
                ensure_ascii=False,
                indent=2
            )
        else:
            result_str = "暂无查询结果"
        
        prompt = SECTION_CONTENT_PROMPT.format(
            section_title=section_title,
            section_description=section_description,
            query_result=result_str,
        )
        
        try:
            result = await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                agent_name="summary",
                stream=False,
            )
            
            return result.get("content", "暂无内容")
            
        except Exception as e:
            print(f"生成章节内容失败: {e}")
            return f"生成失败: {e}"
    
    async def quick_chart(
        self,
        session: Session,
        sql: str,
        chart_purpose: str = None,
    ) -> Dict[str, Any]:
        """
        快速生成单个图表
        
        Args:
            session: 会话
            sql: SQL 查询
            chart_purpose: 图表目的
        """
        # 执行 SQL
        success, data, message = data_executor.execute_sql(session, sql)
        
        if not success:
            return {"error": message}
        
        if not data.get("data"):
            return {"error": "查询结果为空"}
        
        # 生成图表配置
        purpose = chart_purpose or "数据可视化"
        config = await chart_agent.generate_chart_config(
            purpose=purpose,
            sample_data=data["data"],
            session_id=session.session_id,
        )
        
        if "error" in config:
            return config
        
        config["query_data"] = data
        return config


# 全局实例
report_generator = ReportGenerator()

