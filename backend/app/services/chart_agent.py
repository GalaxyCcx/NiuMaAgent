"""
图表配置生成服务
基于 Chart Agent prompt 生成图表配置
"""
import json
from typing import Dict, List, Any, Optional
from ..llm import llm_client
from ..models.session import Session
from .agent_events import AgentContext, agent_event_manager


CHART_SYSTEM_PROMPT = """你是图表配置专家。根据数据和分析需求，选择最佳图表类型并生成配置。

# 支持的图表类型

| 图表类型 | chart_type | 适用场景 |
|---------|------------|---------|
| 柱状图 | bar | 分类对比（<20个分类），数量/金额比较 |
| 折线图 | line | 时间趋势（单一指标随时间变化） |
| 饼图 | pie | 占比分布（<10个分类的比例）|
| 双轴混合图 | dual_axis_mixed | 两个量级差异大的指标对比 |
| 堆叠面积图 | stacked_area | 多个分类占比随时间的变化趋势 |

# 图表选型决策树（严格遵守）

1. **问题涉及"占比分布"？**
   - 是 + 分类<10个 → `pie`
   - 是 + 分类≥10个 → `bar`（按值排序取TOP10）
   - 是 + 要展示占比随时间变化 → `stacked_area`

2. **问题涉及"趋势变化"？**
   - 是 + 单一指标 → `line`
   - 是 + 多个分类各自的趋势 → `stacked_area` 或多条折线 `line`

3. **问题涉及"数量对比"？**
   - 是 + 分类<20个 → `bar`
   - 是 + 分类≥20个 → `bar`（只显示TOP20）

4. **需要同时展示两个不同量级的指标？**
   - 量级差>100倍（如：数量 vs 占比%）→ `dual_axis_mixed`
   - 量级接近 → 普通 `bar` 或 `line`

# 常见错误选型（避免）

| 错误选型 | 正确选型 | 原因 |
|---------|---------|------|
| 用 `pie` 展示50个分类 | `bar` TOP10 | 饼图最多10个扇区 |
| 用 `line` 展示100个开发商数据 | `bar` TOP20 | 折线图用于时间序列 |
| 用 `dual_axis_mixed` 展示两个相同量级字段 | `bar` 多系列 | 双轴用于量级差大的场景 |
| 用单条 `line` 展示多分类占比变化 | `stacked_area` | 占比变化用堆叠面积图 |

# 双轴使用条件

**只有满足以下条件才用 dual_axis_mixed：**
- ✅ 游戏数量(万级) + 平均价格(十级) → 用双轴
- ✅ 总数(千级) + 占比百分比(0-100) → 用双轴
- ❌ 正面评价数 + 负面评价数 → 量级相近，用普通 bar
- ❌ 同一字段放两轴 → 无意义

# 字段名翻译规则

必须将英文字段名翻译为中文：
- total_positive_ratings → 正面评价数
- total_negative_ratings → 负面评价数
- release_year / 年份 → 发布年份
- price → 价格
- count / 数量 → 数量
- ratio / 占比 → 占比(%)
- avg_price → 平均价格
- developer → 开发商
- publisher → 发行商
- genre → 游戏类型

# 铁律

1. x_axis/y_axis 必须从 sample_data 的 key 精确复制
2. data_label 必须是中文
3. 同一字段不能同时出现在左右两个轴
4. 分类超过20个必须限制显示数量

# 输出格式

```json
{
    "chart_type": "bar|line|pie|dual_axis_mixed|stacked_area",
    "title": "图表标题(中文，简洁明了)",
    "data_sources": [
        {
            "data_label": "数据标签(中文)",
            "x_axis": "X轴字段名(原始key)",
            "y_axis": ["Y轴字段名(原始key)"],
            "axis": "primary|secondary",
            "render_type": "bar|line"
        }
    ]
}
```

只输出纯 JSON，不要 markdown 代码块。
"""


class ChartAgent:
    """图表配置生成 Agent"""
    
    async def generate_chart_config(
        self,
        purpose: str,
        sample_data: List[Dict[str, Any]],
        data_schema: Dict[str, Any] = None,
        session_id: str = None,  # 新增：用于事件追踪
    ) -> Dict[str, Any]:
        """
        根据目的和数据生成图表配置
        
        Args:
            purpose: 图表目的描述
            sample_data: 样本数据（用于推断字段）
            data_schema: 数据结构描述（可选）
            session_id: 会话 ID（用于事件追踪）
        
        Returns:
            图表配置字典
        """
        # 创建事件上下文
        agent_ctx = None
        if session_id:
            agent_ctx = AgentContext(
                agent_type="chart",
                agent_label=f"Chart: {purpose[:30]}...",
                session_id=session_id,
            )
            await agent_ctx.emit("start", {"purpose": purpose})
        
        if not sample_data:
            if agent_ctx:
                await agent_ctx.emit("error", {"message": "没有提供样本数据"})
            return {"error": "没有提供样本数据"}
        
        # 构建 prompt
        sample_str = json.dumps(sample_data[:5], ensure_ascii=False, indent=2)
        
        user_prompt = f"""请为以下数据生成图表配置：

**分析目的**: {purpose}

**样本数据** (前5条):
```json
{sample_str}
```

**字段列表**: {list(sample_data[0].keys()) if sample_data else []}

请生成最适合展示这个分析目的的图表配置。"""

        try:
            messages = [
                {"role": "system", "content": CHART_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
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
                agent_name="chart",
                stream=False,
                chunk_callback=on_chunk if agent_ctx else None,
            )
            
            # 发射响应事件
            if agent_ctx:
                await agent_ctx.emit_response(content=result.get("content"))
            
            content = result.get("content", "").strip()
            
            # 解析 JSON（增强版：多重清理）
            config = self._parse_chart_json(content)
            
            if "error" in config:
                raise ValueError(config["error"])
            
            # 添加渲染数据
            config["rendered_data"] = sample_data
            
            # 发射完成事件
            if agent_ctx:
                await agent_ctx.emit("complete", {"chart_type": config.get("chart_type", "unknown")})
            
            return config
            
        except json.JSONDecodeError as e:
            print(f"图表配置解析失败: {e}")
            if agent_ctx:
                await agent_ctx.emit("error", {"message": f"配置解析失败: {e}"})
            # 返回默认柱状图配置
            return self._create_fallback_config(sample_data, purpose)
        except Exception as e:
            print(f"生成图表配置失败: {e}")
            if agent_ctx:
                await agent_ctx.emit("error", {"message": str(e)})
            return {"error": str(e)}
    
    async def generate_charts_for_analysis(
        self,
        session: Session,
        analysis_content: str,
        query_results: List[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        根据分析内容自动生成图表
        
        Args:
            session: 会话
            analysis_content: 分析文本内容
            query_results: 查询结果数据
        
        Returns:
            图表配置列表
        """
        charts = []
        
        if not query_results or len(query_results) == 0:
            return charts
        
        # 分析数据特征
        sample = query_results[0] if query_results else {}
        fields = list(sample.keys())
        
        # 判断是否适合生成图表
        if len(query_results) < 2:
            return charts  # 数据太少，不生成图表
        
        # 识别维度和指标
        dimensions = []
        metrics = []
        
        for field in fields:
            values = [r.get(field) for r in query_results[:10]]
            non_null = [v for v in values if v is not None]
            
            if not non_null:
                continue
            
            first_val = non_null[0]
            if isinstance(first_val, (int, float)):
                metrics.append(field)
            else:
                dimensions.append(field)
        
        # 如果有维度和指标，生成图表
        if dimensions and metrics:
            purpose = f"展示 {dimensions[0]} 维度下的 {', '.join(metrics[:3])} 指标分布"
            config = await self.generate_chart_config(
                purpose=purpose,
                sample_data=query_results,
            )
            
            if "error" not in config:
                charts.append(config)
        
        return charts
    
    def render_chart_data(
        self,
        config: Dict[str, Any],
        full_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        根据配置渲染图表数据
        
        Args:
            config: 图表配置
            full_data: 完整数据
        
        Returns:
            带有渲染数据的配置
        """
        if not config.get("data_sources"):
            return config
        
        for ds in config["data_sources"]:
            x_axis = ds.get("x_axis")
            y_axis = ds.get("y_axis", [])
            filter_config = ds.get("filter", {})
            
            # 应用过滤
            data = full_data.copy()
            
            # TOP N 过滤
            if filter_config.get("top"):
                top_n = filter_config["top"]
                order = filter_config.get("order", "desc")
                
                # 按第一个 Y 轴字段排序
                if y_axis:
                    sort_field = y_axis[0]
                    data.sort(
                        key=lambda x: x.get(sort_field, 0) or 0,
                        reverse=(order == "desc")
                    )
                    data = data[:top_n]
            
            ds["rendered_data"] = data
        
        return config
    
    def _parse_chart_json(self, content: str) -> Dict[str, Any]:
        """
        增强版 JSON 解析（多重清理）
        """
        import re
        
        if not content:
            return {"error": "空内容"}
        
        # 提取 JSON 块
        json_str = content
        if "```json" in content:
            parts = content.split("```json")
            if len(parts) > 1:
                json_str = parts[1].split("```")[0]
        elif "```" in content:
            parts = content.split("```")
            if len(parts) > 1:
                json_str = parts[1].split("```")[0] if len(parts) > 2 else parts[1]
        
        # 查找 JSON 对象
        json_str = json_str.strip()
        if not json_str.startswith("{"):
            match = re.search(r'\{[\s\S]*\}', json_str)
            if match:
                json_str = match.group()
        
        # 清理常见问题
        json_str = json_str.strip()
        # 移除尾部多余逗号
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        # 修复未转义的引号
        json_str = json_str.replace('\\"', '"').replace('""', '"')
        # 移除控制字符
        json_str = re.sub(r'[\x00-\x1f\x7f]', '', json_str)
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[ChartAgent] JSON 解析失败: {e}")
            print(f"[ChartAgent] 原始内容: {json_str[:200]}...")
            return {"error": f"JSON 解析失败: {e}"}
    
    def _create_fallback_config(
        self, 
        sample_data: List[Dict[str, Any]], 
        purpose: str
    ) -> Dict[str, Any]:
        """
        创建回退配置（当 LLM 输出解析失败时）
        """
        if not sample_data:
            return {"error": "无数据", "rendered_data": []}
        
        keys = list(sample_data[0].keys())
        
        # 自动检测字段
        x_field = None
        y_fields = []
        
        for key in keys:
            sample_val = sample_data[0].get(key)
            if isinstance(sample_val, (int, float)):
                y_fields.append(key)
            elif x_field is None:
                x_field = key
        
        if not x_field:
            x_field = keys[0]
        if not y_fields and len(keys) > 1:
            y_fields = [keys[1]]
        
        print(f"[ChartAgent] 使用回退配置: x={x_field}, y={y_fields}")
        
        return {
            "chart_type": "bar",
            "title": purpose[:30] if purpose else "数据分析",
            "data_sources": [{
                "data_label": y_fields[0] if y_fields else "数值",
                "x_axis": x_field,
                "y_axis": y_fields,
                "axis": "primary"
            }],
            "rendered_data": sample_data[:20]  # 限制数据量
        }


# 全局实例
chart_agent = ChartAgent()

