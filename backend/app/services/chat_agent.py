"""
对话 Agent 服务
负责处理用户问答和数据分析请求
"""
import re
import json
from typing import Dict, List, Any, Optional, AsyncGenerator
from ..models.session import Session, session_manager
from ..llm import llm_client
from .context_builder import context_builder
from .data_executor import data_executor


class ChatAgent:
    """对话 Agent - 处理用户问答"""
    
    # 系统提示词中的 SQL 执行指令
    SQL_EXECUTION_PROMPT = """
当你需要查询数据时，请在回答中包含 SQL 语句，使用以下格式：

```sql
SELECT ...
```

系统会自动检测并执行 SQL，将结果返回给你分析。
"""
    
    async def chat(
        self,
        session: Session,
        user_message: str,
        history: List[Dict[str, str]] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        处理用户对话
        
        Args:
            session: 用户会话
            user_message: 用户消息
            history: 历史对话
            stream: 是否流式返回
        
        Returns:
            {
                "content": "回复内容",
                "sql": "执行的SQL（如果有）",
                "data": {查询结果},
                "error": "错误信息（如果有）"
            }
        """
        history = history or []
        
        # 构建系统提示词
        system_prompt = context_builder.build_system_prompt(session)
        
        # 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加历史消息
        for msg in history[-10:]:  # 最多保留最近10轮对话
            messages.append(msg)
        
        # 添加用户消息
        messages.append({"role": "user", "content": user_message})
        
        # 调用 LLM
        result = await llm_client.chat(
            messages=messages,
            agent_name="data",
            stream=False,
        )
        
        response_content = result.get("content", "")
        
        # 检查是否包含 SQL
        sql_result = await self._detect_and_execute_sql(session, response_content)
        
        # 如果执行了 SQL，追加结果分析
        if sql_result["executed"]:
            # 让 LLM 分析查询结果
            analysis = await self._analyze_query_result(
                session, 
                user_message, 
                response_content,
                sql_result
            )
            
            return {
                "content": response_content,
                "analysis": analysis,
                "sql": sql_result["sql"],
                "data": sql_result["data"],
                "error": sql_result.get("error"),
                "usage": result.get("usage"),
            }
        
        return {
            "content": response_content,
            "analysis": None,
            "sql": None,
            "data": None,
            "error": None,
            "usage": result.get("usage"),
        }
    
    async def chat_stream(
        self,
        session: Session,
        user_message: str,
        history: List[Dict[str, str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户对话
        
        Yields:
            {"type": "thinking", "content": "..."} - 思考内容
            {"type": "thinking_end"} - 思考结束
            {"type": "content", "content": "..."} - 文本内容
            {"type": "sql", "sql": "..."} - SQL 语句
            {"type": "sql_executing"} - SQL 执行中
            {"type": "data", "data": {...}} - 查询结果
            {"type": "analysis_start"} - 开始分析
            {"type": "analysis", "content": "..."} - 分析内容（流式）
            {"type": "analysis_end"} - 分析结束
            {"type": "error", "error": "..."} - 错误信息
            {"type": "done"} - 完成
        """
        history = history or []
        
        # 构建系统提示词
        system_prompt = context_builder.build_system_prompt(session)
        
        # 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加历史消息
        for msg in history[-10:]:
            messages.append(msg)
        
        # 添加用户消息
        messages.append({"role": "user", "content": user_message})
        
        # 流式调用 LLM
        full_content = ""
        full_thinking = ""
        is_thinking = False
        
        async for chunk in await llm_client.chat(
            messages=messages,
            agent_name="data",
            stream=True,
        ):
            chunk_type = chunk.get("type", "content")
            chunk_content = chunk.get("content", "")
            
            if chunk_type == "thinking":
                if not is_thinking:
                    is_thinking = True
                    yield {"type": "thinking_start"}
                full_thinking += chunk_content
                yield {"type": "thinking", "content": chunk_content}
            else:
                if is_thinking:
                    is_thinking = False
                    yield {"type": "thinking_end"}
                full_content += chunk_content
                yield {"type": "content", "content": chunk_content}
        
        # 确保思考结束标记已发送
        if is_thinking:
            yield {"type": "thinking_end"}
        
        # 检查是否包含 SQL
        sql_result = await self._detect_and_execute_sql(session, full_content)
        
        if sql_result["executed"]:
            yield {"type": "sql", "sql": sql_result["sql"]}
            yield {"type": "sql_executing"}
            
            if sql_result["data"]:
                yield {"type": "data", "data": sql_result["data"]}
            
            if sql_result.get("error"):
                yield {"type": "error", "error": sql_result["error"]}
            else:
                # 流式生成分析
                yield {"type": "analysis_start"}
                async for analysis_chunk in self._analyze_query_result_stream(
                    session, 
                    user_message, 
                    full_content,
                    sql_result
                ):
                    yield {"type": "analysis", "content": analysis_chunk}
                yield {"type": "analysis_end"}
        
        yield {"type": "done"}
    
    async def _detect_and_execute_sql(
        self, 
        session: Session, 
        content: str
    ) -> Dict[str, Any]:
        """
        检测并执行内容中的 SQL
        
        Returns:
            {
                "executed": bool,
                "sql": str,
                "data": dict,
                "error": str
            }
        """
        # 提取 SQL 代码块
        sql_pattern = r'```sql\s*([\s\S]*?)```'
        matches = re.findall(sql_pattern, content, re.IGNORECASE)
        
        if not matches:
            return {"executed": False, "sql": None, "data": None}
        
        # 执行第一个 SQL
        sql = matches[0].strip()
        
        if not sql:
            return {"executed": False, "sql": None, "data": None}
        
        # 执行查询
        success, data, message = data_executor.execute_sql(session, sql)
        
        return {
            "executed": True,
            "sql": sql,
            "data": data if success else None,
            "error": None if success else message,
        }
    
    async def _analyze_query_result(
        self,
        session: Session,
        user_question: str,
        original_response: str,
        sql_result: Dict[str, Any]
    ) -> Optional[str]:
        """
        分析查询结果
        
        Args:
            session: 用户会话
            user_question: 原始用户问题
            original_response: LLM 的原始回复
            sql_result: SQL 执行结果
        
        Returns:
            分析文本或 None
        """
        if sql_result.get("error"):
            # 查询失败，返回错误说明
            return f"查询执行失败: {sql_result['error']}"
        
        data = sql_result.get("data")
        if not data:
            return None
        
        # 构建分析请求
        prompt = f"""基于以下查询结果，请给出简洁的数据分析和洞察：

用户问题: {user_question}

执行的 SQL:
```sql
{sql_result['sql']}
```

查询结果 ({data['row_count']} 行):
```json
{json.dumps(data['data'][:20], ensure_ascii=False, indent=2)}
```
{f"(显示前 20 行，共 {data['total_count']} 行)" if data.get('truncated') else ""}

请用中文给出：
1. 结果摘要（1-2句话）
2. 关键发现（如果有）
3. 建议的后续分析（如果需要）

保持简洁，不要重复 SQL 语句。"""
        
        try:
            result = await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                agent_name="data",
                stream=False,
            )
            return result.get("content", "")
        except Exception as e:
            print(f"分析查询结果失败: {e}")
            return None
    
    async def _analyze_query_result_stream(
        self,
        session: Session,
        user_question: str,
        original_response: str,
        sql_result: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """
        流式分析查询结果
        
        Yields:
            分析文本片段
        """
        if sql_result.get("error"):
            yield f"查询执行失败: {sql_result['error']}"
            return
        
        data = sql_result.get("data")
        if not data:
            yield "查询无结果"
            return
        
        # 构建分析请求
        prompt = f"""基于以下查询结果，请给出简洁的数据分析和洞察：

用户问题: {user_question}

执行的 SQL:
```sql
{sql_result['sql']}
```

查询结果 ({data['row_count']} 行):
```json
{json.dumps(data['data'][:20], ensure_ascii=False, indent=2)}
```
{f"(显示前 20 行，共 {data['total_count']} 行)" if data.get('truncated') else ""}

请用中文给出：
1. 结果摘要（1-2句话）
2. 关键发现（如果有）
3. 建议的后续分析（如果需要）

保持简洁，不要重复 SQL 语句。"""
        
        try:
            async for chunk in await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                agent_name="data",
                stream=True,
            ):
                # 流式返回只取 content 类型
                if chunk.get("type") == "content":
                    yield chunk.get("content", "")
                elif isinstance(chunk, str):
                    yield chunk
        except Exception as e:
            print(f"分析查询结果失败: {e}")
            yield f"分析失败: {str(e)}"
    
    async def suggest_questions(
        self,
        session: Session,
        limit: int = 5
    ) -> List[str]:
        """
        根据知识库推荐问题
        
        Args:
            session: 用户会话
            limit: 推荐数量
        
        Returns:
            推荐问题列表
        """
        if not session.tables:
            return [
                "请先上传数据文件",
                "支持 CSV 格式的数据文件",
                "上传后我可以帮你分析数据"
            ]
        
        # 构建表摘要
        table_summaries = []
        for table in session.tables:
            desc = table.table_description.get("description", "") if table.table_description else ""
            cols = [c["name"] for c in table.columns[:5]]
            table_summaries.append(f"- {table.table_name}: {desc}，包含字段如 {', '.join(cols)}")
        
        prompt = f"""基于以下数据表，推荐 {limit} 个用户可能会问的数据分析问题：

{chr(10).join(table_summaries)}

要求：
1. 问题要具体、可操作
2. 涵盖不同类型的分析（统计、对比、趋势等）
3. 使用表中实际存在的字段
4. 每个问题一行，不要编号
5. 只输出问题，不要其他内容"""
        
        try:
            result = await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                agent_name="data",
                stream=False,
            )
            
            questions = result.get("content", "").strip().split("\n")
            return [q.strip() for q in questions if q.strip()][:limit]
            
        except Exception as e:
            print(f"生成推荐问题失败: {e}")
            return ["数据有多少行？", "有哪些字段？", "帮我做个数据概览"]


# 创建单例
chat_agent = ChatAgent()

