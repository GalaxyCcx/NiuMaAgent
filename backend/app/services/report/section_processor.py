"""
Section Processor - Section Tool 处理器
负责：处理 Section 参数，调用 Chart Agent 生成图表配置，组装最终结构
"""
import json
import uuid
import hashlib
from typing import Dict, List, Any, Optional, Set

from ..chart_agent import chart_agent


class SectionProcessor:
    """Section 处理器 - 处理 Section 并生成图表配置"""
    
    async def process(
        self,
        section_params: Dict[str, Any],
        search_results: Dict[str, Dict[str, Any]],
        session_id: str = None,  # 新增：用于事件追踪
    ) -> Dict[str, Any]:
        """
        处理 Section，生成完整可渲染的结构
        
        1. 接收 Researcher 的 Section 参数
        2. 遍历 chart_requirements，调用 Chart Agent
        3. 用 charts[] 替换 chart_requirements[]
        4. **去重**：检测并标记重复图表
        5. 返回完整 section
        
        Args:
            section_params: Section 工具参数
            search_results: {data_id: search_result} 字典
            session_id: 会话 ID（用于事件追踪）
        
        Returns:
            完整的 section 数据（可直接渲染）
        """
        self._session_id = session_id
        self._chart_fingerprints: Dict[str, str] = {}  # fingerprint -> first_chart_id
        
        section = {
            "section_id": str(uuid.uuid4()),
            "name": section_params.get("name", ""),
            "discoveries": [],
            "conclusion": section_params.get("conclusion", ""),
            "data_references": section_params.get("data_references", []),
        }
        
        # 获取 discoveries 参数
        discoveries_raw = section_params.get("discoveries", [])
        
        # 如果 discoveries 是字符串，尝试解析为 JSON
        if isinstance(discoveries_raw, str):
            print(f"[SectionProcessor] 警告: discoveries 是字符串，尝试解析 JSON")
            try:
                discoveries_raw = json.loads(discoveries_raw)
            except json.JSONDecodeError as e:
                print(f"[SectionProcessor] JSON 解析失败: {e}")
                discoveries_raw = []
        
        # 确保是列表
        if not isinstance(discoveries_raw, list):
            print(f"[SectionProcessor] 警告: discoveries 类型异常: {type(discoveries_raw)}")
            discoveries_raw = []
        
        # 处理每个 discovery
        for disc_params in discoveries_raw:
            # 处理 LLM 返回字符串而非 dict 的情况
            if isinstance(disc_params, str):
                # 尝试解析为 JSON
                try:
                    disc_params = json.loads(disc_params)
                except json.JSONDecodeError:
                    print(f"[SectionProcessor] 警告: discovery 是字符串且无法解析为 JSON，跳过: {disc_params[:50]}...")
                    continue
            if not isinstance(disc_params, dict):
                print(f"[SectionProcessor] 警告: discovery 类型异常: {type(disc_params)}")
                continue
            discovery = await self._process_discovery(disc_params, search_results)
            section["discoveries"].append(discovery)
        
        # 图表去重：移除重复图表
        section = self._deduplicate_charts(section)
        
        return section
    
    def _calc_chart_fingerprint(self, chart_data: List[Dict], chart_type: str = "") -> str:
        """
        计算图表数据的指纹（用于去重）
        
        指纹基于：
        1. 图表类型
        2. 数据的前 5 条记录的 JSON 字符串
        3. 数据的列名
        """
        if not chart_data:
            return "empty"
        
        # 提取关键特征
        columns = sorted(chart_data[0].keys()) if chart_data else []
        sample = chart_data[:5]
        
        # 构建指纹字符串
        fingerprint_str = f"{chart_type}|{columns}|{json.dumps(sample, sort_keys=True, ensure_ascii=False)}"
        
        # 计算 MD5 哈希
        return hashlib.md5(fingerprint_str.encode()).hexdigest()[:16]
    
    def _deduplicate_charts(self, section: Dict[str, Any]) -> Dict[str, Any]:
        """
        去重图表：检测并移除数据完全相同的图表
        
        策略：
        1. 计算每个图表的数据指纹
        2. 相同指纹的图表只保留第一个
        3. 后续重复图表标记为 _duplicate，不渲染
        """
        seen_fingerprints: Dict[str, str] = {}  # fingerprint -> first_chart_id
        duplicate_count = 0
        
        for disc in section.get("discoveries", []):
            charts = disc.get("charts", [])
            non_duplicate_charts = []
            
            for chart in charts:
                chart_data = chart.get("rendered_data", [])
                chart_type = chart.get("chart_type", "")
                
                fingerprint = self._calc_chart_fingerprint(chart_data, chart_type)
                
                if fingerprint in seen_fingerprints:
                    # 重复图表
                    duplicate_count += 1
                    chart["_duplicate"] = True
                    chart["_duplicate_of"] = seen_fingerprints[fingerprint]
                    print(f"    [去重] 图表 '{chart.get('chart_id', 'unknown')}' 与 '{seen_fingerprints[fingerprint]}' 数据相同，已标记为重复")
                else:
                    # 新图表
                    seen_fingerprints[fingerprint] = chart.get("chart_id", str(uuid.uuid4()))
                    non_duplicate_charts.append(chart)
            
            # 只保留非重复的图表
            disc["charts"] = non_duplicate_charts
        
        if duplicate_count > 0:
            print(f"    [去重统计] 共发现并移除 {duplicate_count} 个重复图表")
        
        return section
    
    async def _process_discovery(
        self,
        disc_params: Dict[str, Any],
        search_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """处理单个 discovery"""
        discovery = {
            "discovery_id": disc_params.get("discovery_id", str(uuid.uuid4())),
            "title": disc_params.get("title", ""),
            "insight": disc_params.get("insight", ""),
            "data_interpretation": disc_params.get("data_interpretation", ""),
            "charts": [],  # 替换 chart_requirements
        }
        
        # 处理 chart_requirements，调用 Chart Agent 生成配置
        chart_requirements = disc_params.get("chart_requirements", [])
        
        for req in chart_requirements:
            chart_config = await self._generate_chart(req, search_results)
            discovery["charts"].append(chart_config)
        
        return discovery
    
    async def _generate_chart(
        self,
        requirement: Dict[str, Any],
        search_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        调用 Chart Agent 生成图表配置
        
        Args:
            requirement: 图表需求
            search_results: 搜索结果
        
        Returns:
            完整的图表配置（包含渲染数据）
        """
        chart_id = requirement.get("chart_id", str(uuid.uuid4()))
        purpose = requirement.get("purpose", "")
        insight_summary = requirement.get("insight_summary", "")
        data_ids = requirement.get("data_ids", [])
        
        # 收集图表数据（优先使用完整数据）
        chart_data = []
        for data_id in data_ids:
            if data_id in search_results:
                result = search_results[data_id]
                # 优先使用 _full_data（完整数据），然后是 sample_data
                data = result.get("_full_data") or result.get("sample_data") or result.get("data_table") or []
                chart_data.extend(data)
        
        if not chart_data:
            print(f"    图表 {chart_id}: 无可用数据")
            return {
                "chart_id": chart_id,
                "error": "无可用数据",
                "purpose": purpose,
            }
        
        # 对于图表，限制合理的数据量（太多会影响渲染性能）
        max_chart_rows = 100
        if len(chart_data) > max_chart_rows:
            # 智能采样：保留头尾和中间等间隔采样
            step = len(chart_data) // (max_chart_rows - 10)
            sampled = [chart_data[i] for i in range(0, len(chart_data), max(1, step))]
            chart_data = sampled[:max_chart_rows]
        
        sample_data = chart_data
        
        print(f"    生成图表配置: {chart_id}, 数据量: {len(sample_data)}")
        
        try:
            # 调用 Chart Agent
            config = await chart_agent.generate_chart_config(
                purpose=f"{purpose}. {insight_summary}" if insight_summary else purpose,
                sample_data=sample_data,
                session_id=self._session_id,  # 传入 session_id 用于事件追踪
            )
            
            # 合并 chart_id
            config["chart_id"] = chart_id
            
            # 确保有渲染数据
            if "rendered_data" not in config:
                config["rendered_data"] = sample_data
            
            # 添加原始 purpose
            config["purpose"] = purpose
            
            return config
            
        except Exception as e:
            print(f"    图表生成失败: {e}")
            return {
                "chart_id": chart_id,
                "error": str(e),
                "purpose": purpose,
                "rendered_data": sample_data,  # 即使失败也提供数据
            }
    
    def validate_section(self, section: Dict[str, Any]) -> List[str]:
        """
        验证 section 结构完整性
        
        Returns:
            问题列表（空列表表示通过）
        """
        issues = []
        
        if not section.get("name"):
            issues.append("缺少章节名称")
        
        discoveries = section.get("discoveries", [])
        if not discoveries:
            issues.append("没有任何发现(discovery)")
        
        for i, disc in enumerate(discoveries):
            if not disc.get("title"):
                issues.append(f"发现 {i+1} 缺少标题")
            
            if not disc.get("insight"):
                issues.append(f"发现 {i+1} 缺少内容")
            
            # 检查标题格式
            title = disc.get("title", "")
            if not any(tag in title for tag in ["【现状】", "【定位】", "【主因】", "【次因】", "【趋势】", "【对比】"]):
                issues.append(f"发现 {i+1} 标题缺少类型标记")
        
        if not section.get("conclusion"):
            issues.append("缺少章节结论")
        
        return issues



