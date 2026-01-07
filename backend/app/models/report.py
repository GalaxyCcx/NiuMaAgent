"""
报告数据模型
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class ChartConfig(BaseModel):
    """图表配置"""
    chart_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chart_type: str  # bar, line, pie, dual_axis_mixed, etc.
    title: str
    data_sources: List[Dict[str, Any]]
    # 渲染后的数据
    rendered_data: Optional[List[Dict[str, Any]]] = None


class ReportSection(BaseModel):
    """报告章节"""
    section_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    content: str  # Markdown 格式的文本内容
    charts: List[ChartConfig] = []
    tables: List[Dict[str, Any]] = []  # 数据表格
    order: int = 0


class Report(BaseModel):
    """报告"""
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str
    summary: str = ""  # 报告摘要
    sections: List[ReportSection] = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: str = "draft"  # draft, generating, completed, error
    
    # 生成过程中的元数据
    generation_log: List[str] = []
    source_questions: List[str] = []  # 触发生成的问题


class ReportManager:
    """报告管理器"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.reports_dir = self.data_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_report_path(self, report_id: str) -> Path:
        return self.reports_dir / f"{report_id}.json"
    
    def create_report(self, session_id: str, title: str, summary: str = "") -> Report:
        """创建新报告"""
        report = Report(
            session_id=session_id,
            title=title,
            summary=summary,
        )
        self.save_report(report)
        return report
    
    def save_report(self, report: Report):
        """保存报告"""
        report.updated_at = datetime.now().isoformat()
        with open(self._get_report_path(report.report_id), "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
    
    def get_report(self, report_id: str) -> Optional[Report]:
        """获取报告"""
        path = self._get_report_path(report_id)
        if not path.exists():
            return None
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Report(**data)
    
    def list_reports(self, session_id: str = None) -> List[Report]:
        """列出报告"""
        reports = []
        for path in self.reports_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                report = Report(**data)
                if session_id is None or report.session_id == session_id:
                    reports.append(report)
            except Exception as e:
                print(f"加载报告失败 {path}: {e}")
        
        # 按创建时间倒序
        reports.sort(key=lambda r: r.created_at, reverse=True)
        return reports
    
    def delete_report(self, report_id: str) -> bool:
        """删除报告"""
        path = self._get_report_path(report_id)
        if path.exists():
            path.unlink()
            return True
        return False
    
    def add_section(self, report_id: str, section: ReportSection) -> Optional[Report]:
        """添加章节"""
        report = self.get_report(report_id)
        if not report:
            return None
        
        section.order = len(report.sections)
        report.sections.append(section)
        self.save_report(report)
        return report
    
    def update_section(self, report_id: str, section_id: str, updates: Dict[str, Any]) -> Optional[Report]:
        """更新章节"""
        report = self.get_report(report_id)
        if not report:
            return None
        
        for section in report.sections:
            if section.section_id == section_id:
                for key, value in updates.items():
                    if hasattr(section, key):
                        setattr(section, key, value)
                break
        
        self.save_report(report)
        return report


# 全局实例
report_manager = ReportManager()

