"""
知识库上下文构建服务
负责将知识库信息构建成 LLM 可理解的上下文
"""
from typing import Dict, List, Any, Optional
from ..models.session import Session, TableKnowledge


class ContextBuilder:
    """上下文构建器 - 将知识库转换为 LLM 上下文"""
    
    def build_system_prompt(
        self, 
        session: Session,
        include_samples: bool = True,
        max_columns_per_table: int = 50
    ) -> str:
        """
        构建系统提示词，包含知识库信息
        
        Args:
            session: 用户会话
            include_samples: 是否包含样本数据
            max_columns_per_table: 每个表最多显示的列数
        
        Returns:
            系统提示词字符串
        """
        if not session.tables:
            return self._build_empty_context_prompt()
        
        # 构建表信息
        tables_context = self._build_tables_context(
            session.tables, 
            include_samples, 
            max_columns_per_table
        )
        
        return f"""你是一个专业的数据分析助手。用户已上传数据文件，你需要基于这些数据回答问题。

## 可用数据表

{tables_context}

## 你的能力

1. **数据理解**：解释数据表的结构、字段含义和数据特征
2. **数据查询**：根据用户问题，生成 SQL 查询语句（使用 pandas 风格）
3. **数据分析**：提供数据洞察、统计摘要、趋势分析等
4. **可视化建议**：推荐合适的图表类型来展示数据

## 回答规则

1. 始终基于已有的数据表来回答问题
2. 如果问题涉及数据查询，先说明查询逻辑，再给出 SQL
3. 如果无法从现有数据回答问题，明确说明原因
4. 使用中文回答
5. 保持回答简洁、专业

## SQL 生成规则

当用户需要查询数据时，生成 SQL 语句，使用以下格式：

```sql
-- 查询说明
SELECT column1, column2, ...
FROM table_name
WHERE condition
ORDER BY column
LIMIT n
```

注意：表名就是文件名（不含扩展名），列名区分大小写。"""
    
    def _build_empty_context_prompt(self) -> str:
        """构建空数据上下文的提示词"""
        return """你是一个专业的数据分析助手。

目前用户还没有上传任何数据文件。请引导用户：

1. 在「数据」标签页上传 CSV 文件
2. 等待系统解析并构建知识库
3. 然后回来继续对话，我将基于数据回答问题

请用友好的方式告诉用户需要先上传数据。"""
    
    def _build_tables_context(
        self, 
        tables: List[TableKnowledge],
        include_samples: bool,
        max_columns: int
    ) -> str:
        """构建表信息上下文"""
        parts = []
        
        for i, table in enumerate(tables, 1):
            table_part = self._build_single_table_context(
                table, i, include_samples, max_columns
            )
            parts.append(table_part)
        
        return "\n\n".join(parts)
    
    def _build_single_table_context(
        self,
        table: TableKnowledge,
        index: int,
        include_samples: bool,
        max_columns: int
    ) -> str:
        """构建单个表的上下文"""
        lines = []
        
        # 表头信息
        lines.append(f"### 表 {index}: `{table.table_name}`")
        lines.append(f"- 来源文件: {table.file_name}")
        lines.append(f"- 数据量: {table.row_count:,} 行 × {table.column_count} 列")
        
        # 表描述
        if table.table_description:
            desc = table.table_description
            if desc.get("description"):
                lines.append(f"- 描述: {desc['description']}")
            if desc.get("main_entities"):
                lines.append(f"- 主要实体: {', '.join(desc['main_entities'])}")
            if desc.get("suggested_analyses"):
                lines.append(f"- 建议分析: {', '.join(desc['suggested_analyses'][:3])}")
        
        # 字段信息
        lines.append("\n**字段列表:**")
        lines.append("| 字段名 | 类型 | 描述 | 样本值 |")
        lines.append("|--------|------|------|--------|")
        
        columns_to_show = table.columns[:max_columns]
        for col in columns_to_show:
            name = col["name"]
            dtype = col.get("inferred_type", "unknown")
            desc = col.get("description", "-")[:30]
            
            # 样本值
            samples = col.get("sample_values", [])[:2]
            sample_str = ", ".join([str(s)[:20] for s in samples]) if samples else "-"
            
            lines.append(f"| `{name}` | {dtype} | {desc} | {sample_str} |")
        
        if len(table.columns) > max_columns:
            lines.append(f"| ... | ... | 还有 {len(table.columns) - max_columns} 个字段 | ... |")
        
        # 样本数据
        if include_samples and table.sample_data:
            lines.append("\n**样本数据 (前3行):**")
            lines.append("```json")
            import json
            # 只取前3行，每行只取前5个字段
            sample_preview = []
            for row in table.sample_data[:3]:
                row_preview = {k: v for k, v in list(row.items())[:5]}
                if len(row) > 5:
                    row_preview["..."] = f"还有 {len(row) - 5} 个字段"
                sample_preview.append(row_preview)
            lines.append(json.dumps(sample_preview, ensure_ascii=False, indent=2))
            lines.append("```")
        
        return "\n".join(lines)
    
    def build_query_context(
        self, 
        session: Session,
        user_question: str
    ) -> str:
        """
        为数据查询构建精简上下文
        
        Args:
            session: 用户会话
            user_question: 用户问题
        
        Returns:
            查询上下文字符串
        """
        if not session.tables:
            return "没有可用的数据表"
        
        lines = ["可用数据表:"]
        
        for table in session.tables:
            lines.append(f"\n表名: {table.table_name}")
            lines.append(f"列: {', '.join([c['name'] for c in table.columns])}")
        
        return "\n".join(lines)
    
    def get_table_schema_for_sql(self, session: Session) -> Dict[str, List[str]]:
        """
        获取用于 SQL 生成的表结构
        
        Returns:
            {表名: [列名列表]}
        """
        schema = {}
        for table in session.tables:
            schema[table.table_name] = [col["name"] for col in table.columns]
        return schema
    
    def build_knowledge_context(
        self,
        session: Session,
        max_columns_per_table: int = 30,
    ) -> str:
        """
        构建报告生成用的知识库上下文
        
        Args:
            session: 用户会话
            max_columns_per_table: 每个表最多显示的列数
        
        Returns:
            知识库上下文字符串（供 Researcher Agent 使用）
        """
        if not session.tables:
            return ""
        
        parts = []
        
        for table in session.tables:
            lines = []
            
            # 表基本信息
            lines.append(f"## 表: {table.table_name}")
            lines.append(f"- 数据量: {table.row_count:,} 行")
            lines.append(f"- 字段数: {table.column_count} 列")
            
            # 表描述
            if table.table_description:
                desc = table.table_description
                if desc.get("description"):
                    lines.append(f"- 描述: {desc['description']}")
                if desc.get("key_dimensions"):
                    lines.append(f"- 关键维度: {', '.join(desc['key_dimensions'])}")
                if desc.get("key_metrics"):
                    lines.append(f"- 关键指标: {', '.join(desc['key_metrics'])}")
            
            # 字段列表
            lines.append("\n### 字段")
            
            # 分类展示
            dimensions = []
            metrics = []
            others = []
            
            for col in table.columns[:max_columns_per_table]:
                col_info = {
                    "name": col["name"],
                    "type": col.get("inferred_type", "unknown"),
                    "desc": col.get("description", ""),
                    "samples": col.get("sample_values", [])[:2],
                }
                
                if col.get("is_dimension"):
                    dimensions.append(col_info)
                elif col.get("is_metric"):
                    metrics.append(col_info)
                else:
                    others.append(col_info)
            
            if dimensions:
                lines.append("\n**维度字段:**")
                for col in dimensions:
                    samples = ", ".join([str(s)[:20] for s in col["samples"]])
                    lines.append(f"- `{col['name']}` ({col['type']}): {col['desc'][:30]} | 样本: {samples}")
            
            if metrics:
                lines.append("\n**指标字段:**")
                for col in metrics:
                    samples = ", ".join([str(s)[:20] for s in col["samples"]])
                    lines.append(f"- `{col['name']}` ({col['type']}): {col['desc'][:30]} | 样本: {samples}")
            
            if others:
                lines.append("\n**其他字段:**")
                for col in others[:10]:  # 其他字段只显示前10个
                    samples = ", ".join([str(s)[:20] for s in col["samples"]])
                    lines.append(f"- `{col['name']}` ({col['type']}): {col['desc'][:30]}")
                
                if len(others) > 10:
                    lines.append(f"- ... 还有 {len(others) - 10} 个字段")
            
            parts.append("\n".join(lines))
        
        return "\n\n---\n\n".join(parts)


# 创建单例
context_builder = ContextBuilder()

