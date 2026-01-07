"""
会话和数据存储模型
"""
import json
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ProcessingProgress(BaseModel):
    """处理进度信息"""
    current_step: str = ""  # 当前步骤名称
    step_index: int = 0  # 当前步骤索引 (1-based)
    total_steps: int = 0  # 总步骤数
    percent: int = 0  # 完成百分比 (0-100)
    started_at: Optional[str] = None  # 开始时间
    estimated_remaining_seconds: Optional[int] = None  # 预计剩余秒数
    logs: List[str] = Field(default_factory=list)  # 处理日志


class FileInfo(BaseModel):
    """文件基本信息"""
    file_size_mb: float = 0  # 文件大小 (MB)
    row_count: Optional[int] = None  # 行数
    column_count: Optional[int] = None  # 列数
    encoding: Optional[str] = None  # 文件编码


class UploadedFile(BaseModel):
    """上传的文件信息"""
    file_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_name: str
    stored_path: str
    file_size: int
    status: str = "pending"  # pending, processing, ready, error
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    # 新增字段
    file_info: Optional[FileInfo] = None  # 文件基本信息
    progress: Optional[ProcessingProgress] = None  # 处理进度


class TableKnowledge(BaseModel):
    """表的知识库信息"""
    table_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_id: str
    table_name: str
    file_name: str
    row_count: int
    column_count: int
    columns: List[Dict[str, Any]]
    statistics: Dict[str, Any]
    sample_data: List[Dict[str, Any]]
    table_description: Optional[Dict[str, Any]] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class Session(BaseModel):
    """用户会话"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    files: List[UploadedFile] = Field(default_factory=list)
    tables: List[TableKnowledge] = Field(default_factory=list)
    conversations: List[Dict[str, Any]] = Field(default_factory=list)


class SessionManager:
    """会话管理器 - 负责会话的创建、存储和检索"""
    
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # 使用项目根目录下的 data 目录
            self.data_dir = Path(__file__).parent.parent.parent.parent / "data"
        else:
            self.data_dir = Path(data_dir)
        self.sessions_dir = self.data_dir / "sessions"
        self.uploads_dir = self.data_dir / "uploads"
        self._ensure_dirs()
        self._sessions: Dict[str, Session] = {}
    
    def _ensure_dirs(self):
        """确保目录存在"""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
    
    def create_session(self) -> Session:
        """创建新会话"""
        session = Session()
        self._sessions[session.session_id] = session
        self._save_session(session)
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        # 先从内存获取
        if session_id in self._sessions:
            return self._sessions[session_id]
        
        # 从文件加载
        session_file = self.sessions_dir / f"{session_id}.json"
        if session_file.exists():
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = Session(**data)
            self._sessions[session_id] = session
            return session
        
        return None
    
    def get_or_create_session(self, session_id: Optional[str] = None) -> Session:
        """获取或创建会话"""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
        return self.create_session()
    
    def update_session(self, session: Session):
        """更新会话"""
        session.updated_at = datetime.now().isoformat()
        self._sessions[session.session_id] = session
        self._save_session(session)
    
    def _save_session(self, session: Session):
        """保存会话到文件"""
        session_file = self.sessions_dir / f"{session.session_id}.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session.model_dump(), f, ensure_ascii=False, indent=2)
    
    def add_file(self, session: Session, file_info: UploadedFile) -> Session:
        """添加文件到会话"""
        session.files.append(file_info)
        self.update_session(session)
        return session
    
    def update_file_status(
        self, 
        session: Session, 
        file_id: str, 
        status: str, 
        error: Optional[str] = None
    ) -> Session:
        """更新文件状态"""
        for f in session.files:
            if f.file_id == file_id:
                f.status = status
                if error:
                    f.error_message = error
                break
        self.update_session(session)
        return session
    
    def update_file_info(
        self,
        session: Session,
        file_id: str,
        file_info: FileInfo
    ) -> Session:
        """更新文件基本信息"""
        for f in session.files:
            if f.file_id == file_id:
                f.file_info = file_info
                break
        self.update_session(session)
        return session
    
    def update_file_progress(
        self,
        session: Session,
        file_id: str,
        progress: ProcessingProgress
    ) -> Session:
        """更新文件处理进度"""
        for f in session.files:
            if f.file_id == file_id:
                f.progress = progress
                break
        self.update_session(session)
        return session
    
    def add_file_log(
        self,
        session: Session,
        file_id: str,
        log_message: str
    ) -> Session:
        """添加处理日志"""
        for f in session.files:
            if f.file_id == file_id:
                if f.progress is None:
                    f.progress = ProcessingProgress()
                # 添加时间戳
                timestamp = datetime.now().strftime("%H:%M:%S")
                f.progress.logs.append(f"[{timestamp}] {log_message}")
                # 只保留最近50条日志
                if len(f.progress.logs) > 50:
                    f.progress.logs = f.progress.logs[-50:]
                break
        self.update_session(session)
        return session
    
    def add_table_knowledge(self, session: Session, knowledge: TableKnowledge) -> Session:
        """添加表知识库"""
        session.tables.append(knowledge)
        self.update_session(session)
        return session
    
    def get_all_knowledge(self, session: Session) -> List[Dict[str, Any]]:
        """获取会话的所有知识库"""
        return [t.model_dump() for t in session.tables]
    
    def delete_file(self, session: Session, file_id: str) -> Session:
        """删除文件记录"""
        import os
        for f in session.files:
            if f.file_id == file_id:
                # 删除物理文件
                if os.path.exists(f.stored_path):
                    try:
                        os.remove(f.stored_path)
                    except Exception as e:
                        print(f"删除文件失败: {e}")
                break
        
        session.files = [f for f in session.files if f.file_id != file_id]
        self.update_session(session)
        return session
    
    def delete_table(self, session: Session, table_id: str) -> Session:
        """删除表知识库"""
        session.tables = [t for t in session.tables if t.table_id != table_id]
        self.update_session(session)
        return session
    
    def clear_session(self, session: Session) -> Session:
        """清空会话的所有文件和表"""
        import shutil
        
        # 删除上传目录
        session_upload_dir = self.uploads_dir / session.session_id
        if session_upload_dir.exists():
            try:
                shutil.rmtree(session_upload_dir)
            except Exception as e:
                print(f"删除上传目录失败: {e}")
        
        session.files = []
        session.tables = []
        self.update_session(session)
        return session
    
    def delete_session(self, session_id: str) -> bool:
        """完全删除会话"""
        import shutil
        
        # 从内存移除
        if session_id in self._sessions:
            del self._sessions[session_id]
        
        # 删除会话文件
        session_file = self.sessions_dir / f"{session_id}.json"
        if session_file.exists():
            try:
                session_file.unlink()
            except Exception as e:
                print(f"删除会话文件失败: {e}")
                return False
        
        # 删除上传目录
        session_upload_dir = self.uploads_dir / session_id
        if session_upload_dir.exists():
            try:
                shutil.rmtree(session_upload_dir)
            except Exception as e:
                print(f"删除上传目录失败: {e}")
        
        return True
    
    def get_upload_path(self, session_id: str, filename: str) -> Path:
        """获取文件上传路径"""
        session_upload_dir = self.uploads_dir / session_id
        session_upload_dir.mkdir(parents=True, exist_ok=True)
        return session_upload_dir / filename
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话"""
        sessions = []
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data["session_id"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "file_count": len(data.get("files", [])),
                    "table_count": len(data.get("tables", [])),
                })
            except Exception as e:
                print(f"读取会话文件失败 {session_file}: {e}")
        return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)


# 创建单例
session_manager = SessionManager()

