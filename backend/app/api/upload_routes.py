"""
文件上传 API 路由
"""
import os
import shutil
import time
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from pydantic import BaseModel

from ..models.session import (
    session_manager, 
    UploadedFile, 
    TableKnowledge,
    FileInfo,
    ProcessingProgress
)
from ..services.data_parser import DataParser
from ..services.knowledge_builder import knowledge_builder

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("file_processor")

router = APIRouter()


class UploadResponse(BaseModel):
    """上传响应"""
    success: bool
    session_id: str
    files: List[dict]
    message: str


class KnowledgeResponse(BaseModel):
    """知识库响应"""
    success: bool
    tables: List[dict]
    message: str


class ProgressTracker:
    """进度跟踪器"""
    
    # 处理步骤定义
    STEPS = [
        ("读取文件", 5),      # 步骤名, 预计占比
        ("解析CSV结构", 10),
        ("分析字段类型", 15),
        ("生成统计信息", 20),
        ("提取样本数据", 5),
        ("生成字段描述", 35),  # LLM 调用，最耗时
        ("构建知识库", 5),
        ("保存结果", 5),
    ]
    
    STEPS_NO_LLM = [
        ("读取文件", 10),
        ("解析CSV结构", 20),
        ("分析字段类型", 25),
        ("生成统计信息", 25),
        ("提取样本数据", 10),
        ("保存结果", 10),
    ]
    
    def __init__(self, session_id: str, file_id: str, use_llm: bool = True):
        self.session_id = session_id
        self.file_id = file_id
        self.use_llm = use_llm
        self.steps = self.STEPS if use_llm else self.STEPS_NO_LLM
        self.total_steps = len(self.steps)
        self.current_step_idx = 0
        self.start_time = time.time()
        self.step_start_time = time.time()
        
    def _get_session(self):
        return session_manager.get_session(self.session_id)
    
    def _log(self, message: str, level: str = "INFO"):
        """记录日志到控制台和会话"""
        # 控制台日志
        log_msg = f"[{self.file_id[:8]}] {message}"
        if level == "ERROR":
            logger.error(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        
        # 会话日志
        session = self._get_session()
        if session:
            session_manager.add_file_log(session, self.file_id, message)
    
    def start_step(self, step_name: str = None):
        """开始一个步骤"""
        self.step_start_time = time.time()
        
        if step_name is None and self.current_step_idx < len(self.steps):
            step_name = self.steps[self.current_step_idx][0]
        
        # 计算进度百分比
        percent = 0
        for i in range(self.current_step_idx):
            percent += self.steps[i][1]
        
        # 计算预计剩余时间
        elapsed = time.time() - self.start_time
        estimated_remaining = None
        if percent > 0:
            total_estimated = elapsed / (percent / 100)
            estimated_remaining = int(total_estimated - elapsed)
        
        # 更新进度
        progress = ProcessingProgress(
            current_step=step_name,
            step_index=self.current_step_idx + 1,
            total_steps=self.total_steps,
            percent=percent,
            started_at=datetime.fromtimestamp(self.start_time).isoformat(),
            estimated_remaining_seconds=estimated_remaining,
            logs=[]
        )
        
        session = self._get_session()
        if session:
            # 保留现有日志
            for f in session.files:
                if f.file_id == self.file_id and f.progress:
                    progress.logs = f.progress.logs
                    break
            session_manager.update_file_progress(session, self.file_id, progress)
        
        self._log(f"开始: {step_name} (步骤 {self.current_step_idx + 1}/{self.total_steps})")
    
    def complete_step(self):
        """完成当前步骤"""
        if self.current_step_idx < len(self.steps):
            step_name = self.steps[self.current_step_idx][0]
            step_time = time.time() - self.step_start_time
            self._log(f"完成: {step_name} (耗时 {step_time:.1f}秒)")
            self.current_step_idx += 1
    
    def finish(self, success: bool = True, error: str = None):
        """完成所有处理"""
        total_time = time.time() - self.start_time
        if success:
            self._log(f"✓ 处理完成，总耗时 {total_time:.1f}秒")
        else:
            self._log(f"✗ 处理失败: {error}", "ERROR")
        
        # 更新最终进度
        progress = ProcessingProgress(
            current_step="完成" if success else "失败",
            step_index=self.total_steps if success else self.current_step_idx,
            total_steps=self.total_steps,
            percent=100 if success else int((self.current_step_idx / self.total_steps) * 100),
            started_at=datetime.fromtimestamp(self.start_time).isoformat(),
            estimated_remaining_seconds=0,
            logs=[]
        )
        
        session = self._get_session()
        if session:
            for f in session.files:
                if f.file_id == self.file_id and f.progress:
                    progress.logs = f.progress.logs
                    break
            session_manager.update_file_progress(session, self.file_id, progress)


# 用于跟踪需要取消的任务（在函数定义前声明）
_cancelled_tasks_internal = set()


def _check_cancelled(file_id: str) -> bool:
    """检查任务是否被取消"""
    return file_id in _cancelled_tasks_internal


async def process_file_async(
    session_id: str, 
    file_id: str, 
    file_path: str,
    file_size: int,
    generate_descriptions: bool = True
):
    """异步处理文件 - 解析并构建知识库"""
    session = session_manager.get_session(session_id)
    if not session:
        return
    
    # 初始化进度跟踪器
    tracker = ProgressTracker(session_id, file_id, use_llm=generate_descriptions)
    
    def check_cancelled():
        """检查是否被取消，如果被取消则抛出异常"""
        if _check_cancelled(file_id):
            raise InterruptedError("任务已被用户取消")
    
    try:
        # 更新状态为处理中
        session_manager.update_file_status(session, file_id, "processing")
        
        # ===== 步骤 1: 读取文件 =====
        check_cancelled()
        tracker.start_step()
        file_size_mb = file_size / (1024 * 1024)
        tracker._log(f"文件大小: {file_size_mb:.2f} MB")
        tracker.complete_step()
        
        # ===== 步骤 2: 解析 CSV 结构 =====
        check_cancelled()
        tracker.start_step()
        parser = DataParser()
        parsed_data = parser.parse_csv(file_path)
        
        # 更新文件信息
        file_info = FileInfo(
            file_size_mb=round(file_size_mb, 2),
            row_count=parsed_data["row_count"],
            column_count=parsed_data["column_count"],
            encoding="UTF-8"  # TODO: 从解析器获取
        )
        session = session_manager.get_session(session_id)
        session_manager.update_file_info(session, file_id, file_info)
        
        tracker._log(f"行数: {parsed_data['row_count']:,} 行")
        tracker._log(f"列数: {parsed_data['column_count']} 列")
        tracker.complete_step()
        
        # ===== 步骤 3: 分析字段类型 =====
        check_cancelled()
        tracker.start_step()
        columns = parsed_data["columns"]
        dimension_count = sum(1 for c in columns if c.get("is_dimension"))
        metric_count = sum(1 for c in columns if c.get("is_metric"))
        tracker._log(f"维度字段: {dimension_count} 个, 指标字段: {metric_count} 个")
        tracker.complete_step()
        
        # ===== 步骤 4: 生成统计信息 =====
        check_cancelled()
        tracker.start_step()
        stats = parsed_data.get("statistics", {})
        if stats.get("potential_primary_key"):
            tracker._log(f"识别到主键字段: {stats['potential_primary_key']}")
        if stats.get("duplicate_rows", 0) > 0:
            tracker._log(f"发现重复行: {stats['duplicate_rows']} 行")
        tracker.complete_step()
        
        # ===== 步骤 5: 提取样本数据 =====
        check_cancelled()
        tracker.start_step()
        sample_count = len(parsed_data.get("sample_data", []))
        tracker._log(f"提取样本数据: {sample_count} 行")
        tracker.complete_step()
        
        # ===== 步骤 6: 生成字段描述 (如果启用 LLM) =====
        check_cancelled()
        if generate_descriptions:
            tracker.start_step()
            tracker._log("正在调用 LLM 生成字段描述...")
            total_columns = len(columns)
            
            # 构建知识库（包含 LLM 调用）
            knowledge = await knowledge_builder.build_knowledge_base(
                parsed_data,
                generate_descriptions=True
            )
            tracker._log(f"已完成 {total_columns} 个字段的描述生成")
            tracker.complete_step()
            
            # ===== 步骤 7: 构建知识库 =====
            tracker.start_step()
        else:
            # 不使用 LLM
            knowledge = await knowledge_builder.build_knowledge_base(
                parsed_data,
                generate_descriptions=False
            )
        
        # ===== 最后步骤: 保存结果 =====
        tracker.start_step()
        
        # 创建知识库记录
        table_knowledge = TableKnowledge(
            file_id=file_id,
            table_name=knowledge["table_name"],
            file_name=knowledge["file_name"],
            row_count=knowledge["row_count"],
            column_count=knowledge["column_count"],
            columns=knowledge["columns"],
            statistics=knowledge["statistics"],
            sample_data=knowledge["sample_data"],
            table_description=knowledge.get("table_description"),
        )
        
        # 保存知识库
        session = session_manager.get_session(session_id)
        session_manager.add_table_knowledge(session, table_knowledge)
        
        # 更新文件状态为就绪
        session_manager.update_file_status(session, file_id, "ready")
        tracker.complete_step()
        
        tracker.finish(success=True)
        
    except Exception as e:
        # 更新文件状态为错误
        session = session_manager.get_session(session_id)
        session_manager.update_file_status(session, file_id, "error", str(e))
        tracker.finish(success=False, error=str(e))
        logger.exception(f"处理文件失败 [{file_id}]")


@router.post("/upload", response_model=UploadResponse)
async def upload_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    generate_descriptions: bool = Form(True),
):
    """
    上传 CSV 文件
    
    - 支持多文件上传
    - 自动创建或使用现有会话
    - 后台异步处理文件并构建知识库
    """
    # 获取或创建会话
    session = session_manager.get_or_create_session(session_id)
    
    uploaded_files = []
    
    for file in files:
        # 验证文件类型
        if not file.filename.lower().endswith('.csv'):
            raise HTTPException(
                status_code=400, 
                detail=f"只支持 CSV 文件，{file.filename} 不是有效的 CSV 文件"
            )
        
        # 保存文件
        upload_path = session_manager.get_upload_path(session.session_id, file.filename)
        
        try:
            with open(upload_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")
        
        # 获取文件大小
        file_size = os.path.getsize(upload_path)
        
        # 创建初始文件信息
        initial_file_info = FileInfo(
            file_size_mb=round(file_size / (1024 * 1024), 2)
        )
        
        # 创建初始进度
        initial_progress = ProcessingProgress(
            current_step="等待处理",
            step_index=0,
            total_steps=8 if generate_descriptions else 6,
            percent=0,
            logs=[]
        )
        
        # 创建文件记录
        file_info = UploadedFile(
            original_name=file.filename,
            stored_path=str(upload_path),
            file_size=file_size,
            status="pending",
            file_info=initial_file_info,
            progress=initial_progress,
        )
        
        # 添加到会话
        session = session_manager.add_file(session, file_info)
        uploaded_files.append(file_info.model_dump())
        
        # 添加后台处理任务
        background_tasks.add_task(
            process_file_async,
            session.session_id,
            file_info.file_id,
            str(upload_path),
            file_size,
            generate_descriptions,
        )
        
        logger.info(f"文件已加入处理队列: {file.filename} ({file_size / 1024 / 1024:.2f} MB)")
    
    return UploadResponse(
        success=True,
        session_id=session.session_id,
        files=uploaded_files,
        message=f"成功上传 {len(uploaded_files)} 个文件，正在后台处理中",
    )


@router.get("/upload/status/{session_id}")
async def get_upload_status(session_id: str):
    """获取上传文件的处理状态（包含详细进度）"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    files_status = []
    for f in session.files:
        file_status = {
            "file_id": f.file_id,
            "original_name": f.original_name,
            "status": f.status,
            "error_message": f.error_message,
            "file_info": f.file_info.model_dump() if f.file_info else None,
            "progress": f.progress.model_dump() if f.progress else None,
        }
        files_status.append(file_status)
    
    # 检查是否所有文件都已处理完成
    all_ready = all(f.status in ["ready", "error"] for f in session.files)
    processing_count = sum(1 for f in session.files if f.status == "processing")
    ready_count = sum(1 for f in session.files if f.status == "ready")
    error_count = sum(1 for f in session.files if f.status == "error")
    pending_count = sum(1 for f in session.files if f.status == "pending")
    
    return {
        "session_id": session_id,
        "files": files_status,
        "all_ready": all_ready,
        "summary": {
            "total": len(session.files),
            "pending": pending_count,
            "processing": processing_count,
            "ready": ready_count,
            "error": error_count,
        }
    }


@router.get("/upload/logs/{session_id}/{file_id}")
async def get_file_logs(session_id: str, file_id: str):
    """获取单个文件的处理日志"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    for f in session.files:
        if f.file_id == file_id:
            return {
                "file_id": file_id,
                "original_name": f.original_name,
                "status": f.status,
                "logs": f.progress.logs if f.progress else [],
            }
    
    raise HTTPException(status_code=404, detail="文件不存在")


@router.get("/knowledge/{session_id}", response_model=KnowledgeResponse)
async def get_knowledge_base(session_id: str):
    """获取会话的知识库"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    tables = session_manager.get_all_knowledge(session)
    
    return KnowledgeResponse(
        success=True,
        tables=tables,
        message=f"共 {len(tables)} 个数据表",
    )


@router.get("/knowledge/{session_id}/{table_id}")
async def get_table_detail(session_id: str, table_id: str):
    """获取单个表的详细知识库信息"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    for table in session.tables:
        if table.table_id == table_id:
            return {
                "success": True,
                "table": table.model_dump(),
            }
    
    raise HTTPException(status_code=404, detail="数据表不存在")


@router.get("/sessions")
async def list_sessions():
    """列出所有会话"""
    sessions = session_manager.list_sessions()
    return {
        "success": True,
        "sessions": sessions,
        "total": len(sessions),
    }


@router.get("/session/{session_id}")
async def get_session_detail(session_id: str):
    """获取会话详情"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {
        "success": True,
        "session": session.model_dump(),
    }


# ==================== 删除和中断 API ====================

def is_task_cancelled(file_id: str) -> bool:
    """检查任务是否被取消"""
    return file_id in _cancelled_tasks_internal


def mark_task_cancelled(file_id: str):
    """标记任务为取消"""
    _cancelled_tasks_internal.add(file_id)


def clear_cancelled_mark(file_id: str):
    """清除取消标记"""
    _cancelled_tasks_internal.discard(file_id)


@router.delete("/file/{session_id}/{file_id}")
async def delete_file(session_id: str, file_id: str):
    """删除单个文件（同时取消正在进行的处理）"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 查找文件
    file_found = False
    for f in session.files:
        if f.file_id == file_id:
            file_found = True
            # 如果正在处理，标记为取消
            if f.status == "processing":
                mark_task_cancelled(file_id)
            break
    
    if not file_found:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 删除文件记录
    session_manager.delete_file(session, file_id)
    
    # 同时删除关联的表
    session = session_manager.get_session(session_id)
    tables_to_delete = [t.table_id for t in session.tables if t.file_id == file_id]
    for table_id in tables_to_delete:
        session_manager.delete_table(session, table_id)
    
    logger.info(f"已删除文件: {file_id}")
    
    return {
        "success": True,
        "message": "文件已删除",
        "deleted_tables": len(tables_to_delete)
    }


@router.delete("/table/{session_id}/{table_id}")
async def delete_table(session_id: str, table_id: str):
    """删除单个表"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 查找表
    table_found = False
    for t in session.tables:
        if t.table_id == table_id:
            table_found = True
            break
    
    if not table_found:
        raise HTTPException(status_code=404, detail="表不存在")
    
    session_manager.delete_table(session, table_id)
    logger.info(f"已删除表: {table_id}")
    
    return {"success": True, "message": "表已删除"}


@router.post("/cancel/{session_id}/{file_id}")
async def cancel_processing(session_id: str, file_id: str):
    """取消正在处理的任务"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 查找文件
    for f in session.files:
        if f.file_id == file_id:
            if f.status != "processing":
                return {"success": False, "message": "文件未在处理中"}
            
            # 标记为取消
            mark_task_cancelled(file_id)
            
            # 更新状态为已取消
            session_manager.update_file_status(session, file_id, "error", "用户取消")
            session_manager.add_file_log(session, file_id, "⚠️ 处理已被用户取消")
            
            logger.info(f"已取消处理: {file_id}")
            return {"success": True, "message": "处理已取消"}
    
    raise HTTPException(status_code=404, detail="文件不存在")


@router.delete("/session/{session_id}/clear")
async def clear_session(session_id: str):
    """清空会话的所有文件和表"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 取消所有正在处理的任务
    for f in session.files:
        if f.status == "processing":
            mark_task_cancelled(f.file_id)
    
    session_manager.clear_session(session)
    logger.info(f"已清空会话: {session_id}")
    
    return {"success": True, "message": "会话已清空"}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """完全删除会话"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 取消所有正在处理的任务
    for f in session.files:
        if f.status == "processing":
            mark_task_cancelled(f.file_id)
    
    success = session_manager.delete_session(session_id)
    
    if success:
        logger.info(f"已删除会话: {session_id}")
        return {"success": True, "message": "会话已删除"}
    else:
        raise HTTPException(status_code=500, detail="删除会话失败")
