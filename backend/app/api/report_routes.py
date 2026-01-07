"""
报告生成 API 路由
"""
import json
import uuid
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..models.session import session_manager
from ..services.report import center_agent


router = APIRouter(prefix="/report", tags=["report"])


# ============ 请求/响应模型 ============

class GenerateReportRequest(BaseModel):
    """生成报告请求"""
    session_id: str
    request: str = Field(..., description="用户的报告需求描述")
    stream: bool = Field(default=True, description="是否流式返回")


class ReportListItem(BaseModel):
    """报告列表项"""
    report_id: str
    title: str
    summary: str = ""
    status: str
    section_count: int = 0
    created_at: str


class ReportListResponse(BaseModel):
    """报告列表响应"""
    reports: List[ReportListItem]


# ============ 报告存储 ============

# 简单的内存存储（生产环境应使用数据库）
_reports_store: dict = {}


def save_report(report: dict):
    """保存报告"""
    report_id = report.get("report_id")
    if report_id:
        _reports_store[report_id] = report
        
        # 同时保存到文件
        reports_dir = Path(__file__).parent.parent.parent.parent / "data" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = reports_dir / f"{report_id}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)


def get_report(report_id: str) -> Optional[dict]:
    """获取报告"""
    if report_id in _reports_store:
        return _reports_store[report_id]
    
    # 尝试从文件加载
    reports_dir = Path(__file__).parent.parent.parent.parent / "data" / "reports"
    report_file = reports_dir / f"{report_id}.json"
    
    if report_file.exists():
        with open(report_file, "r", encoding="utf-8") as f:
            report = json.load(f)
        _reports_store[report_id] = report
        return report
    
    return None


def list_reports(session_id: str) -> List[dict]:
    """列出会话的所有报告"""
    reports = []
    reports_dir = Path(__file__).parent.parent.parent.parent / "data" / "reports"
    
    if not reports_dir.exists():
        return reports
    
    for report_file in reports_dir.glob("*.json"):
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                report = json.load(f)
            
            # 简单过滤（实际应该在报告中存储 session_id）
            reports.append({
                "report_id": report.get("report_id", ""),
                "title": report.get("title", "未命名报告"),
                "summary": report.get("summary", "")[:100],
                "status": report.get("status", "unknown"),
                "section_count": len(report.get("sections", [])),
                "created_at": report.get("created_at", ""),
            })
        except Exception as e:
            print(f"读取报告文件失败 {report_file}: {e}")
    
    # 按创建时间排序
    reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return reports


def delete_report(report_id: str) -> bool:
    """删除报告"""
    if report_id in _reports_store:
        del _reports_store[report_id]
    
    reports_dir = Path(__file__).parent.parent.parent.parent / "data" / "reports"
    report_file = reports_dir / f"{report_id}.json"
    
    if report_file.exists():
        try:
            report_file.unlink()
            return True
        except Exception as e:
            print(f"删除报告文件失败: {e}")
            return False
    
    return False


# ============ API 路由 ============

@router.post("/generate")
async def generate_report(request: GenerateReportRequest):
    """
    生成报告（流式）
    
    使用 SSE 流式返回生成进度和结果
    """
    # 验证会话
    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if not session.tables:
        raise HTTPException(status_code=400, detail="请先上传数据文件")
    
    async def event_stream():
        """SSE 事件流生成器"""
        final_report = None
        
        try:
            async for event in center_agent.generate_report(
                session=session,
                user_request=request.request,
                stream=True,
            ):
                event_type = event.get("type", "unknown")
                
                # 格式化为 SSE
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                
                # 保存最终报告
                if event_type == "complete":
                    final_report = event.get("report")
                    if final_report:
                        # 添加 session_id
                        final_report["session_id"] = request.session_id
                        save_report(final_report)
                
                elif event_type == "error":
                    # 保存失败状态
                    error_report = {
                        "report_id": str(uuid.uuid4()),
                        "session_id": request.session_id,
                        "title": "报告生成失败",
                        "status": "error",
                        "error": event.get("message", "Unknown error"),
                        "created_at": datetime.now().isoformat(),
                    }
                    save_report(error_report)
            
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            print(f"报告生成流错误: {e}")
            import traceback
            traceback.print_exc()
            
            error_event = {
                "type": "error",
                "message": str(e),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/list/{session_id}", response_model=ReportListResponse)
async def get_report_list(session_id: str):
    """获取会话的报告列表"""
    reports = list_reports(session_id)
    return {"reports": reports}


@router.get("/{report_id}")
async def get_report_detail(report_id: str):
    """获取报告详情"""
    report = get_report(report_id)
    
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    
    return {"report": report}


@router.delete("/{report_id}")
async def delete_report_endpoint(report_id: str):
    """删除报告"""
    success = delete_report(report_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="报告不存在或删除失败")
    
    return {"success": True, "message": "报告已删除"}
