"""
NL2SQL Agent - 自然语言转 SQL
负责：将自然语言查询需求转换为可执行的 SQL 语句
"""
import json
import re
from typing import Dict, List, Any, Optional, Tuple

from ...llm import llm_client
from ...models.session import Session
from ..agent_events import AgentContext, agent_event_manager


class NL2SQLAgent:
    """
    NL2SQL Agent - 将自然语言转换为 SQL
    
    特点：
    1. 根据表结构和字段信息生成精确 SQL
    2. 支持复杂查询（JOIN、聚合、子查询）
    3. 自动处理字段类型和格式
    4. SQL 安全检查（防止危险操作）
    """
    
    def __init__(self):
        self.system_prompt = """你是一个专业的数据分析 SQL 专家。根据用户的分析需求和数据表结构，生成能直接用于可视化的 SQL。

## 核心原则

**直接计算用户需要的指标，不要只返回原始数据。**

## ⚠️⚠️⚠️ SQLite 语法限制（必须严格遵守）⚠️⚠️⚠️

本系统使用 **SQLite** 数据库，以下是允许和禁止的语法：

### ✅ 允许的语法模式

```sql
-- 1. 单表查询 + 聚合
SELECT 字段, COUNT(*), SUM(字段), AVG(字段) FROM 表 GROUP BY 字段

-- 2. 简单 WHERE 条件
WHERE 字段 = '值'
WHERE 字段 BETWEEN '开始' AND '结束'
WHERE 字段 >= '值' AND 字段 <= '值'
WHERE 字段 LIKE '%关键词%'
WHERE 字段 IN ('值1', '值2', '值3')

-- 3. 日期函数（SQLite 专用）
strftime('%Y', 日期字段) AS 年份
strftime('%Y-%m', 日期字段) AS 年月
strftime('%m', 日期字段) AS 月份

-- 4. CASE WHEN 条件统计
COUNT(CASE WHEN 条件 THEN 1 END) AS 计数

-- 5. 简单 JOIN（最多 2 表）
FROM 表1 LEFT JOIN 表2 ON 表1.字段 = 表2.字段

-- 6. ORDER BY + LIMIT
ORDER BY 字段 DESC LIMIT 100
```

### ❌ 禁止的语法（会导致执行失败）

```sql
-- 1. 嵌套子查询（绝对禁止）
WHERE 字段 IN (SELECT ...)  -- ❌ 禁止
WHERE EXISTS (SELECT ...)   -- ❌ 禁止
FROM (SELECT * FROM ...)    -- ❌ 禁止

-- 2. 窗口函数（SQLite 版本不支持）
ROW_NUMBER() OVER (...)     -- ❌ 禁止
RANK() OVER (...)           -- ❌ 禁止

-- 3. MySQL/PostgreSQL 专用语法
DATE_FORMAT(字段, '%Y')     -- ❌ 用 strftime 代替
YEAR(字段)                  -- ❌ 用 strftime('%Y', 字段) 代替
MONTH(字段)                 -- ❌ 用 strftime('%m', 字段) 代替
EXTRACT(YEAR FROM 字段)     -- ❌ 用 strftime 代替

-- 4. UNION / INTERSECT / EXCEPT
SELECT ... UNION SELECT ... -- ❌ 禁止

-- 5. 自定义函数
CUSTOM_FUNC(...)            -- ❌ 禁止
```

## 特殊字符字段名处理

当字段名包含特殊字符时，必须用**反引号**包裹：
```sql
-- 字段名包含 = 号、空格、减号等
SELECT `EGP=X` AS 汇率 FROM USD2EGP
SELECT `24K - Local Price/Sell` AS 金价 FROM data
```

## 别名规则

**别名必须使用中文**，便于图表展示。

⚠️ **以数字开头的别名需要加反引号**：
```sql
-- 正确
SELECT 字段 AS `24K金价` FROM 表
SELECT 字段 AS `22K价格` FROM 表

-- 错误（会报错）
SELECT 字段 AS 24K金价 FROM 表  -- ❌ 数字开头必须加引号
```

普通别名不需要引号：
```sql
SELECT 字段 AS 年份 FROM 表      -- ✅
SELECT 字段 AS 平均价格 FROM 表  -- ✅
```

## 分析意图 → SQL 模式映射

| 用户意图 | SQL 模式 |
|---------|---------|
| "占比/比例/百分比" | `ROUND(COUNT(CASE WHEN 条件 THEN 1 END) * 100.0 / COUNT(*), 2) AS 占比` |
| "趋势/变化/增长" | `GROUP BY strftime('%Y', 日期) ORDER BY 年份` |
| "分布/分类统计" | `GROUP BY 分类字段` + `COUNT(*)` |
| "TOP/排名" | `ORDER BY 字段 DESC LIMIT N` |
| "平均/均值" | `AVG(字段)` |

## 完整示例

**需求**: "分析2023年各月汇率变化趋势"

**正确 SQL**:
```sql
SELECT 
    strftime('%Y-%m', Date) AS 月份,
    AVG(`EGP=X`) AS 平均汇率,
    MAX(`EGP=X`) AS 最高汇率,
    MIN(`EGP=X`) AS 最低汇率
FROM USD2EGP
WHERE strftime('%Y', Date) = '2023'
GROUP BY 月份
ORDER BY 月份
LIMIT 100
```

**需求**: "查看本地黄金价格概况"

**正确 SQL**:
```sql
SELECT 
    Date AS 日期,
    `24K - Local Price/Sell` AS `24K售价`,
    `24K - Local Price/Buy` AS `24K买价`,
    `22K - Local Price/Sell` AS `22K售价`
FROM data
ORDER BY Date DESC
LIMIT 100
```

## 铁律

1. **只用 SELECT**，禁止 INSERT/UPDATE/DELETE/DROP
2. **必须有 LIMIT**（默认 100，最大 200）
3. **字段名必须精确匹配**表结构，区分大小写
4. **特殊字符字段名用反引号**包裹
5. **禁止嵌套子查询**，用简单 JOIN 代替

## 输出格式

调用 GenerateSQL 工具输出结果。"""

    async def generate_sql(
        self,
        query_intent: str,
        table_schemas: List[Dict[str, Any]],
        context: Optional[str] = None,
        session_id: str = None,  # 新增：用于事件追踪
    ) -> Dict[str, Any]:
        """
        根据查询意图生成 SQL
        
        Args:
            query_intent: 自然语言查询意图（如："查询2020年后发布的游戏数量"）
            table_schemas: 表结构列表 [{"table_name": "", "columns": [{"name": "", "type": "", "sample": ""}]}]
            context: 额外上下文（如报告主题、前一步分析结果）
            session_id: 会话 ID（用于事件追踪）
        
        Returns:
            {"sql": "SELECT ...", "explanation": "SQL 解释", "expected_columns": ["col1", "col2"]}
        """
        # 创建事件上下文
        agent_ctx = None
        if session_id:
            agent_ctx = AgentContext(
                agent_type="nl2sql",
                agent_label=f"NL2SQL: {query_intent[:30]}...",
                session_id=session_id,
            )
            await agent_ctx.emit("start", {"query_intent": query_intent})
        # 获取可用表名列表
        available_tables = [s.get("table_name", "") for s in table_schemas]
        
        # 构建表结构描述
        schema_text = self._format_table_schemas(table_schemas)
        
        user_message = f"""请根据以下需求生成 SQL 查询语句。

## 查询需求
{query_intent}

## 可用表结构
{schema_text}
"""
        if context:
            user_message += f"\n## 上下文\n{context}\n"
        
        user_message += "\n请调用 GenerateSQL 工具生成 SQL。"
        
        # 工具定义
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "GenerateSQL",
                    "description": "生成 SQL 查询语句",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "完整的 SQL SELECT 语句"
                            },
                            "explanation": {
                                "type": "string",
                                "description": "SQL 语句的简要解释"
                            },
                            "expected_columns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "预期返回的列名列表"
                            }
                        },
                        "required": ["sql", "explanation", "expected_columns"]
                    }
                }
            }
        ]
        
        try:
            print(f"[NL2SQL] 生成 SQL...")
            print(f"  意图: {query_intent[:80]}...")
            
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
                agent_name="nl2sql",
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
                if tool_call["function"]["name"] == "GenerateSQL":
                    args = json.loads(tool_call["function"]["arguments"])
                    sql = args.get("sql", "")
                    
                    # 安全检查
                    is_safe, error = self._validate_sql(sql, available_tables)
                    if not is_safe:
                        print(f"[NL2SQL] SQL 安全检查失败: {error}")
                        return {
                            "success": False,
                            "error": f"SQL 安全检查失败: {error}",
                            "sql": sql,
                        }
                    
                    # 添加 LIMIT（如果没有）
                    sql = self._ensure_limit(sql)
                    
                    print(f"[NL2SQL] 生成成功:")
                    print(f"  SQL: {sql[:100]}...")
                    
                    # 发射完成事件
                    if agent_ctx:
                        await agent_ctx.emit("complete", {"sql": sql})
                    
                    return {
                        "success": True,
                        "sql": sql,
                        "explanation": args.get("explanation", ""),
                        "expected_columns": args.get("expected_columns", []),
                    }
            
            # 没有工具调用，尝试从文本中提取 SQL
            content = result.get("content", "")
            sql_match = re.search(r'```sql\s*(.*?)\s*```', content, re.DOTALL | re.IGNORECASE)
            if sql_match:
                sql = sql_match.group(1).strip()
                is_safe, error = self._validate_sql(sql, available_tables)
                if is_safe:
                    sql = self._ensure_limit(sql)
                    return {
                        "success": True,
                        "sql": sql,
                        "explanation": "从文本中提取的 SQL",
                        "expected_columns": [],
                    }
            
            return {
                "success": False,
                "error": "未能生成有效的 SQL",
                "raw_response": content[:500],
            }
            
        except Exception as e:
            print(f"[NL2SQL] 生成失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 发射错误事件
            if agent_ctx:
                await agent_ctx.emit("error", {"message": str(e)})
            return {
                "success": False,
                "error": str(e),
            }
    
    def _format_table_schemas(self, schemas: List[Dict[str, Any]]) -> str:
        """格式化表结构为文本"""
        result = []
        
        for schema in schemas:
            table_name = schema.get("table_name", "unknown")
            columns = schema.get("columns", [])
            row_count = schema.get("row_count", 0)
            
            lines = [f"### 表: `{table_name}` (共 {row_count} 行)"]
            lines.append("| 字段名 | 类型 | 示例值 |")
            lines.append("|--------|------|--------|")
            
            for col in columns[:30]:  # 限制列数
                name = col.get("name", "")
                dtype = col.get("type", col.get("dtype", "unknown"))
                sample = str(col.get("sample", col.get("sample_values", "")))[:50]
                lines.append(f"| `{name}` | {dtype} | {sample} |")
            
            result.append("\n".join(lines))
        
        return "\n\n".join(result)
    
    def _validate_sql(self, sql: str, available_tables: List[str] = None) -> Tuple[bool, str]:
        """验证 SQL 安全性、表名有效性和复杂度"""
        sql_upper = sql.upper().strip()
        
        # 禁止的关键词
        forbidden = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 'ALTER', 
                     'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE', '--', ';--']
        
        for keyword in forbidden:
            if keyword in sql_upper:
                return False, f"包含禁止的关键词: {keyword}"
        
        # 必须是 SELECT 语句
        if not sql_upper.startswith('SELECT'):
            return False, "必须是 SELECT 语句"
        
        # 检查是否包含多个语句（分号分隔）
        sql_clean = sql.strip().rstrip(';')
        if ';' in sql_clean:
            return False, "不允许多语句查询"
        
        # ⚠️ 禁止嵌套子查询（性能限制）
        # 检测 WHERE ... IN (SELECT ...) 模式
        if re.search(r'\bIN\s*\(\s*SELECT\b', sql_upper):
            return False, "禁止使用嵌套子查询 IN (SELECT ...)，请使用 JOIN 或简化查询"
        
        # 检测 WHERE EXISTS (SELECT ...) 模式
        if re.search(r'\bEXISTS\s*\(\s*SELECT\b', sql_upper):
            return False, "禁止使用 EXISTS 子查询，请简化查询逻辑"
        
        # 检测多层嵌套 FROM (SELECT ...) 模式
        if re.search(r'\bFROM\s*\(\s*SELECT\b', sql_upper):
            return False, "禁止使用 FROM 子查询，请直接查询表"
        
        # 检测复杂窗口函数
        if re.search(r'\b(ROW_NUMBER|RANK|DENSE_RANK|NTILE)\s*\(\s*\)\s*OVER\b', sql_upper):
            return False, "禁止使用复杂窗口函数，请使用 GROUP BY + ORDER BY"
        
        # 限制 JOIN 数量（最多 2 个）
        join_count = len(re.findall(r'\bJOIN\b', sql_upper))
        if join_count > 2:
            return False, f"JOIN 过多（{join_count}个），最多允许 2 个表关联"
        
        # 检查表名是否有效
        if available_tables:
            # 提取 SQL 中的表名（FROM 和 JOIN 后面的表名）
            table_pattern = r'\b(?:FROM|JOIN)\s+[`"]?(\w+)[`"]?'
            referenced_tables = re.findall(table_pattern, sql, re.IGNORECASE)
            
            # 排除 SQL 关键字和函数名
            sql_keywords = {'select', 'from', 'where', 'and', 'or', 'in', 'not', 
                           'null', 'is', 'like', 'between', 'exists', 'case',
                           'when', 'then', 'else', 'end', 'as', 'on', 'using',
                           'left', 'right', 'inner', 'outer', 'cross', 'natural',
                           'group', 'order', 'by', 'having', 'limit', 'offset',
                           'union', 'intersect', 'except', 'distinct', 'all',
                           'count', 'sum', 'avg', 'min', 'max', 'coalesce'}
            
            available_lower = [t.lower() for t in available_tables]
            
            for table in referenced_tables:
                table_lower = table.lower()
                if table_lower in sql_keywords:
                    continue
                if table_lower not in available_lower:
                    return False, f"表 '{table}' 不在可用表列表中: {available_tables}"
        
        return True, ""
    
    def _ensure_limit(self, sql: str, max_limit: int = 200) -> str:
        """确保 SQL 包含 LIMIT（默认 200，防止数据量过大）"""
        sql_upper = sql.upper()
        
        if 'LIMIT' not in sql_upper:
            sql = sql.rstrip(';').strip()
            sql += f" LIMIT {max_limit}"
        else:
            # 检查现有 LIMIT 是否过大
            limit_match = re.search(r'LIMIT\s+(\d+)', sql_upper)
            if limit_match:
                current_limit = int(limit_match.group(1))
                if current_limit > max_limit:
                    sql = re.sub(r'LIMIT\s+\d+', f'LIMIT {max_limit}', sql, flags=re.IGNORECASE)
        
        return sql
    
    def validate_result(
        self,
        query_intent: str,
        result_columns: List[str],
        result_data: List[Dict[str, Any]],
    ) -> Tuple[bool, str, List[str]]:
        """
        验证 SQL 执行结果是否符合分析需求
        
        Args:
            query_intent: 原始查询意图
            result_columns: 结果列名列表
            result_data: 结果数据
        
        Returns:
            (是否有效, 问题描述, 建议)
        """
        issues = []
        suggestions = []
        intent_lower = query_intent.lower()
        columns_str = " ".join(result_columns).lower()
        
        # 检查结果是否为空
        if not result_data:
            return False, "查询结果为空", ["检查筛选条件是否过严", "确认数据表中有符合条件的数据"]
        
        # 检查是否只返回了原始数据（没有聚合）
        if len(result_data) > 100:
            # 如果结果超过 100 行，很可能是返回了原始数据而没有聚合
            if any(kw in intent_lower for kw in ["趋势", "变化", "增长", "分布", "统计"]):
                issues.append("结果行数过多，可能缺少聚合")
                suggestions.append("应该使用 GROUP BY 进行聚合")
        
        # 检查"占比"需求
        if any(kw in intent_lower for kw in ["占比", "比例", "百分比"]):
            ratio_keywords = ["占比", "比例", "百分比", "ratio", "percent", "%"]
            has_ratio = any(kw in columns_str for kw in ratio_keywords)
            if not has_ratio:
                issues.append("需求涉及'占比/比例'，但结果中没有相关计算字段")
                suggestions.append("SQL 应包含: ROUND(COUNT(condition) * 100.0 / COUNT(*), 2) AS xxx占比")
        
        # 检查"趋势/变化"需求
        if any(kw in intent_lower for kw in ["趋势", "变化", "增长"]):
            time_keywords = ["年", "月", "日", "year", "month", "date", "时间"]
            has_time = any(kw in columns_str for kw in time_keywords)
            if not has_time:
                issues.append("需求涉及'趋势/变化'，但结果中没有时间维度")
                suggestions.append("SQL 应包含时间字段: strftime('%Y', date) AS 年份")
        
        # 检查是否有中文别名
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in columns_str)
        if not has_chinese:
            issues.append("结果列名全是英文，缺少中文别名")
            suggestions.append("SQL 应使用中文别名: SELECT field AS 中文名称")
        
        if issues:
            return False, "; ".join(issues), suggestions
        
        return True, "", []


# 全局实例
nl2sql_agent = NL2SQLAgent()

