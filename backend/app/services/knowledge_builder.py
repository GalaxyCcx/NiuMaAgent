"""
知识库构建服务
负责使用 LLM 生成字段描述和表描述
"""
import json
from typing import Dict, List, Any, Optional
from ..llm import llm_client


class KnowledgeBuilder:
    """知识库构建器 - 使用 LLM 生成数据描述"""
    
    # 批量字段描述 Prompt（一次处理多个字段）
    BATCH_FIELD_DESCRIPTION_PROMPT = """你是一个数据分析专家。请为以下字段生成简洁的业务描述（每个20字以内）。

{fields_info}

请严格按以下 JSON 格式返回，key 为字段名，value 为描述：
{example_json}

要求：
1. 描述要简洁准确，说明字段的业务含义
2. 必须为每个字段都生成描述
3. 只输出 JSON，不要任何其他内容"""

    TABLE_DESCRIPTION_PROMPT = """你是一个数据分析专家。请根据以下表信息，生成表的业务描述和分析建议。

表名: {table_name}
行数: {row_count}
列数: {column_count}

字段列表:
{fields_info}

请生成以下内容（JSON格式）:
{{
    "description": "表的业务描述（50字以内）",
    "main_entities": ["主要业务实体1", "主要业务实体2"],
    "key_dimensions": ["关键维度字段1", "关键维度字段2"],
    "key_metrics": ["关键指标字段1", "关键指标字段2"],
    "suggested_analyses": ["建议分析1", "建议分析2", "建议分析3"]
}}

只输出 JSON，不要任何其他内容。"""

    # 限制需要 LLM 生成描述的字段数量
    MAX_FIELDS_FOR_LLM = 50
    # 每批处理的字段数量
    BATCH_SIZE = 10
    
    def _format_field_info(self, col: Dict[str, Any]) -> str:
        """格式化单个字段信息用于批量 Prompt"""
        info_parts = [f"字段名: {col['name']}"]
        info_parts.append(f"  类型: {col['inferred_type']}")
        
        # 样本值（最多3个，避免过长）
        samples = col.get("sample_values", [])[:3]
        if samples:
            # 截断过长的样本值
            truncated_samples = []
            for s in samples:
                s_str = str(s)
                if len(s_str) > 50:
                    s_str = s_str[:47] + "..."
                truncated_samples.append(s_str)
            info_parts.append(f"  样本: {', '.join(truncated_samples)}")
        
        # 额外信息
        if col.get("stats"):
            stats = col["stats"]
            info_parts.append(f"  范围: {stats.get('min')} ~ {stats.get('max')}")
        
        return "\n".join(info_parts)
    
    async def _process_batch(
        self, 
        batch: List[Dict[str, Any]], 
        batch_idx: int,
        total_batches: int
    ) -> Dict[str, str]:
        """处理一批字段，返回 {字段名: 描述} 字典"""
        descriptions = {}
        field_names = [col["name"] for col in batch]
        
        try:
            # 构建字段信息
            fields_info = "\n\n".join([
                f"【字段 {i+1}】\n{self._format_field_info(col)}"
                for i, col in enumerate(batch)
            ])
            
            # 构建示例 JSON
            example_json = json.dumps(
                {name: "字段描述" for name in field_names},
                ensure_ascii=False,
                indent=2
            )
            
            prompt = self.BATCH_FIELD_DESCRIPTION_PROMPT.format(
                fields_info=fields_info,
                example_json=example_json
            )
            
            print(f"\n{'='*60}")
            print(f"批量生成字段描述: 第 {batch_idx + 1}/{total_batches} 批 ({len(batch)} 个字段)")
            print(f"字段: {', '.join(field_names)}")
            print(f"{'='*60}")
            print("LLM 输出:", flush=True)
            
            result = await llm_client.chat_with_console_stream(
                messages=[{"role": "user", "content": prompt}],
                agent_name="data",
                prefix=">>> ",
            )
            
            print(f"{'='*60}")
            content = result.get("content", "").strip()
            
            # 解析 JSON（处理可能的 markdown 代码块）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            parsed = json.loads(content.strip())
            
            # 提取描述
            for name in field_names:
                if name in parsed:
                    desc = str(parsed[name]).strip()[:50]
                    descriptions[name] = desc
                else:
                    # 字段名可能有大小写差异，尝试不区分大小写匹配
                    matched = False
                    for key, value in parsed.items():
                        if key.lower() == name.lower():
                            descriptions[name] = str(value).strip()[:50]
                            matched = True
                            break
                    if not matched:
                        descriptions[name] = "数据字段"
            
            print(f"  批次 {batch_idx + 1} 完成，成功解析 {len(descriptions)} 个字段描述")
            
        except json.JSONDecodeError as e:
            print(f"  批次 {batch_idx + 1} JSON 解析失败: {e}")
            # 使用默认描述
            for col in batch:
                descriptions[col["name"]] = f"{col.get('semantic_type', 'text')}类型字段"
                
        except Exception as e:
            print(f"  批次 {batch_idx + 1} 处理失败: {e}")
            for col in batch:
                descriptions[col["name"]] = f"{col.get('semantic_type', 'text')}类型字段"
        
        return descriptions
    
    async def generate_field_descriptions(
        self, 
        columns: List[Dict[str, Any]],
        max_fields: int = None
    ) -> Dict[str, str]:
        """
        批量为字段生成业务描述
        
        Args:
            columns: 字段信息列表
            max_fields: 最大处理字段数，超过此数量的字段使用默认描述
        
        Returns:
            {字段名: 描述} 的字典
        """
        descriptions = {}
        max_fields = max_fields or self.MAX_FIELDS_FOR_LLM
        
        # 如果字段数量超过限制，只处理最重要的字段
        if len(columns) > max_fields:
            # 优先处理：维度字段 > ID字段 > 指标字段
            priority_columns = []
            other_columns = []
            
            for col in columns:
                if col.get("is_dimension") or col.get("semantic_type") == "id":
                    priority_columns.append(col)
                elif col.get("is_metric"):
                    priority_columns.append(col)
                else:
                    other_columns.append(col)
            
            # 选择前 max_fields 个字段
            columns_to_process = (priority_columns + other_columns)[:max_fields]
            columns_skipped = [c for c in columns if c not in columns_to_process]
            
            print(f"字段过多({len(columns)}个)，只为前{max_fields}个重要字段生成描述，其余{len(columns_skipped)}个使用默认描述")
            
            # 为跳过的字段设置默认描述
            for col in columns_skipped:
                descriptions[col["name"]] = f"{col.get('semantic_type', 'text')}类型字段"
        else:
            columns_to_process = columns
        
        # 分批处理
        total = len(columns_to_process)
        batches = [
            columns_to_process[i:i + self.BATCH_SIZE] 
            for i in range(0, total, self.BATCH_SIZE)
        ]
        total_batches = len(batches)
        
        print(f"开始批量生成字段描述: 共 {total} 个字段，分 {total_batches} 批处理（每批 {self.BATCH_SIZE} 个）")
        
        for batch_idx, batch in enumerate(batches):
            batch_descriptions = await self._process_batch(batch, batch_idx, total_batches)
            descriptions.update(batch_descriptions)
        
        print(f"字段描述生成完成，共 {len(descriptions)} 个字段")
        return descriptions
    
    async def generate_table_description(
        self,
        table_name: str,
        row_count: int,
        column_count: int,
        columns: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        为表生成业务描述和分析建议
        
        Args:
            table_name: 表名
            row_count: 行数
            column_count: 列数
            columns: 字段信息列表
        
        Returns:
            表描述信息
        """
        try:
            # 构建字段信息
            fields_info = []
            for col in columns[:20]:  # 限制字段数量
                field_line = f"- {col['name']} ({col['semantic_type']})"
                if col.get("sample_values"):
                    field_line += f": {col['sample_values'][0]}"
                fields_info.append(field_line)
            
            prompt = self.TABLE_DESCRIPTION_PROMPT.format(
                table_name=table_name,
                row_count=row_count,
                column_count=column_count,
                fields_info="\n".join(fields_info),
            )
            
            print(f"\n{'='*60}")
            print(f"生成表描述: {table_name}")
            print(f"{'='*60}")
            print("LLM 输出:", flush=True)
            
            result = await llm_client.chat_with_console_stream(
                messages=[{"role": "user", "content": prompt}],
                agent_name="data",
                prefix=">>> ",
            )
            
            print(f"{'='*60}")
            content = result.get("content", "").strip()
            
            # 尝试解析 JSON
            # 处理可能的 markdown 代码块
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content)
            
        except json.JSONDecodeError as e:
            print(f"解析表描述失败: {e}")
            return {
                "description": f"包含 {row_count} 行 {column_count} 列的数据表",
                "main_entities": [],
                "key_dimensions": [c["name"] for c in columns if c.get("is_dimension")][:3],
                "key_metrics": [c["name"] for c in columns if c.get("is_metric")][:3],
                "suggested_analyses": ["数据概览分析", "趋势分析", "分布分析"],
            }
        except Exception as e:
            print(f"生成表描述失败: {e}")
            return {
                "description": f"数据表 {table_name}",
                "main_entities": [],
                "key_dimensions": [],
                "key_metrics": [],
                "suggested_analyses": [],
            }
    
    async def build_knowledge_base(
        self,
        parsed_data: Dict[str, Any],
        generate_descriptions: bool = True
    ) -> Dict[str, Any]:
        """
        构建完整的知识库
        
        Args:
            parsed_data: 数据解析结果
            generate_descriptions: 是否使用 LLM 生成描述
        
        Returns:
            知识库数据
        """
        knowledge = {
            "table_name": parsed_data["file_name"].replace(".csv", ""),
            "file_name": parsed_data["file_name"],
            "row_count": parsed_data["row_count"],
            "column_count": parsed_data["column_count"],
            "columns": parsed_data["columns"],
            "statistics": parsed_data["statistics"],
            "sample_data": parsed_data["sample_data"],
        }
        
        if generate_descriptions:
            # 生成字段描述
            field_descriptions = await self.generate_field_descriptions(
                parsed_data["columns"]
            )
            
            # 更新字段信息
            for col in knowledge["columns"]:
                col["description"] = field_descriptions.get(col["name"], "")
            
            # 生成表描述
            table_info = await self.generate_table_description(
                knowledge["table_name"],
                knowledge["row_count"],
                knowledge["column_count"],
                knowledge["columns"],
            )
            knowledge["table_description"] = table_info
        else:
            # 使用默认描述
            for col in knowledge["columns"]:
                col["description"] = f"{col['semantic_type']}类型字段"
            knowledge["table_description"] = {
                "description": f"数据表 {knowledge['table_name']}",
                "main_entities": [],
                "key_dimensions": [c["name"] for c in knowledge["columns"] if c.get("is_dimension")][:3],
                "key_metrics": [c["name"] for c in knowledge["columns"] if c.get("is_metric")][:3],
                "suggested_analyses": [],
            }
        
        return knowledge


# 创建单例
knowledge_builder = KnowledgeBuilder()

