"""
数据解析服务
负责 CSV 文件的解析、类型推断和统计信息生成
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import re


class DataParser:
    """CSV 数据解析器"""
    
    # 日期格式模式
    DATE_PATTERNS = [
        r'^\d{4}-\d{2}-\d{2}$',  # 2024-01-01
        r'^\d{4}/\d{2}/\d{2}$',  # 2024/01/01
        r'^\d{2}-\d{2}-\d{4}$',  # 01-01-2024
        r'^\d{2}/\d{2}/\d{4}$',  # 01/01/2024
        r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$',  # 2024-01-01 12:00:00
    ]
    
    def __init__(self):
        self.df: Optional[pd.DataFrame] = None
        self.file_path: Optional[str] = None
    
    def parse_csv(
        self, 
        file_path: str, 
        encoding: str = 'utf-8',
        sample_rows: int = 1000
    ) -> Dict[str, Any]:
        """
        解析 CSV 文件
        
        Args:
            file_path: CSV 文件路径
            encoding: 文件编码
            sample_rows: 用于类型推断的样本行数
        
        Returns:
            解析结果，包含表结构、统计信息等
        """
        self.file_path = file_path
        
        # 尝试不同编码读取
        encodings_to_try = [encoding, 'utf-8', 'gbk', 'gb2312', 'latin1']
        
        for enc in encodings_to_try:
            try:
                self.df = pd.read_csv(file_path, encoding=enc, low_memory=False)
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                raise ValueError(f"无法解析 CSV 文件: {e}")
        
        if self.df is None:
            raise ValueError("无法识别文件编码")
        
        # 获取表信息
        result = {
            "file_name": Path(file_path).name,
            "file_path": file_path,
            "row_count": len(self.df),
            "column_count": len(self.df.columns),
            "columns": self._analyze_columns(),
            "sample_data": self._get_sample_data(5),
            "statistics": self._generate_statistics(),
        }
        
        return result
    
    def _analyze_columns(self) -> List[Dict[str, Any]]:
        """分析每个列的类型和属性"""
        columns = []
        
        for col in self.df.columns:
            col_data = self.df[col]
            
            # 推断类型
            inferred_type, semantic_type = self._infer_column_type(col, col_data)
            
            # 获取样本值
            non_null_values = col_data.dropna()
            sample_values = non_null_values.head(5).tolist() if len(non_null_values) > 0 else []
            
            # 统计信息
            null_count = col_data.isna().sum()
            unique_count = col_data.nunique()
            
            column_info = {
                "name": col,
                "dtype": str(col_data.dtype),
                "inferred_type": inferred_type,
                "semantic_type": semantic_type,
                "null_count": int(null_count),
                "null_ratio": round(null_count / len(self.df), 4) if len(self.df) > 0 else 0,
                "unique_count": int(unique_count),
                "sample_values": [str(v)[:100] for v in sample_values],  # 限制长度
                "is_dimension": semantic_type in ["category", "date", "id"],
                "is_metric": semantic_type in ["integer", "decimal", "percentage"],
            }
            
            # 添加数值统计
            if inferred_type in ["integer", "decimal"]:
                numeric_data = pd.to_numeric(col_data, errors='coerce')
                column_info["stats"] = {
                    "min": float(numeric_data.min()) if not pd.isna(numeric_data.min()) else None,
                    "max": float(numeric_data.max()) if not pd.isna(numeric_data.max()) else None,
                    "mean": round(float(numeric_data.mean()), 2) if not pd.isna(numeric_data.mean()) else None,
                    "median": float(numeric_data.median()) if not pd.isna(numeric_data.median()) else None,
                }
            
            # 添加分类统计
            if semantic_type == "category" and unique_count <= 50:
                value_counts = col_data.value_counts().head(10)
                column_info["top_values"] = [
                    {"value": str(k), "count": int(v)} 
                    for k, v in value_counts.items()
                ]
            
            columns.append(column_info)
        
        return columns
    
    def _infer_column_type(self, col_name: str, col_data: pd.Series) -> Tuple[str, str]:
        """
        推断列的数据类型和语义类型
        
        Returns:
            (数据类型, 语义类型)
            数据类型: integer, decimal, text, date, boolean
            语义类型: id, category, date, integer, decimal, percentage, text
        """
        # 获取非空样本
        non_null = col_data.dropna()
        if len(non_null) == 0:
            return "text", "text"
        
        sample = non_null.head(100)
        col_name_lower = col_name.lower()
        
        # 检查是否为 ID 字段
        if any(kw in col_name_lower for kw in ['id', '_id', 'code', 'key']):
            return "text", "id"
        
        # 检查原始 dtype
        dtype = col_data.dtype
        
        # 布尔类型
        if dtype == bool or set(sample.unique()).issubset({True, False, 0, 1, '0', '1', 'true', 'false', 'True', 'False'}):
            return "boolean", "category"
        
        # 数值类型
        if pd.api.types.is_numeric_dtype(dtype):
            # 检查是否为百分比
            if any(kw in col_name_lower for kw in ['rate', 'ratio', 'percent', '率', '比', '%']):
                return "decimal", "percentage"
            
            # 检查是否为整数
            if pd.api.types.is_integer_dtype(dtype):
                return "integer", "integer"
            else:
                # 检查小数是否实际为整数
                if all(float(x).is_integer() for x in sample if pd.notna(x)):
                    return "integer", "integer"
                return "decimal", "decimal"
        
        # 字符串类型 - 进一步分析
        sample_str = sample.astype(str)
        
        # 检查是否为日期
        if self._is_date_column(sample_str):
            return "date", "date"
        
        # 检查是否为数值字符串
        numeric_ratio = self._get_numeric_ratio(sample_str)
        if numeric_ratio > 0.8:
            # 检查是否包含小数
            has_decimal = any('.' in str(x) for x in sample)
            if has_decimal:
                return "decimal", "decimal"
            return "integer", "integer"
        
        # 分类 vs 文本
        unique_ratio = len(sample.unique()) / len(sample)
        if unique_ratio < 0.5 or col_data.nunique() <= 100:
            return "text", "category"
        
        return "text", "text"
    
    def _is_date_column(self, sample: pd.Series) -> bool:
        """检查是否为日期列"""
        match_count = 0
        for value in sample.head(20):
            value_str = str(value).strip()
            for pattern in self.DATE_PATTERNS:
                if re.match(pattern, value_str):
                    match_count += 1
                    break
        return match_count / min(len(sample), 20) > 0.7
    
    def _get_numeric_ratio(self, sample: pd.Series) -> float:
        """获取可转换为数值的比例"""
        numeric_count = 0
        for value in sample:
            try:
                float(str(value).replace(',', ''))
                numeric_count += 1
            except:
                pass
        return numeric_count / len(sample) if len(sample) > 0 else 0
    
    def _get_sample_data(self, n: int = 5) -> List[Dict[str, Any]]:
        """获取样本数据"""
        sample_df = self.df.head(n)
        records = []
        for _, row in sample_df.iterrows():
            record = {}
            for col in self.df.columns:
                value = row[col]
                if pd.isna(value):
                    record[col] = None
                elif isinstance(value, (np.integer, np.floating)):
                    record[col] = float(value) if isinstance(value, np.floating) else int(value)
                else:
                    record[col] = str(value)[:200]  # 限制长度
            records.append(record)
        return records
    
    def _generate_statistics(self) -> Dict[str, Any]:
        """生成整体统计信息"""
        stats = {
            "total_rows": len(self.df),
            "total_columns": len(self.df.columns),
            "memory_usage_mb": round(self.df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
            "duplicate_rows": int(self.df.duplicated().sum()),
        }
        
        # 按类型统计列
        numeric_cols = self.df.select_dtypes(include=[np.number]).columns.tolist()
        text_cols = self.df.select_dtypes(include=['object']).columns.tolist()
        
        stats["numeric_columns"] = len(numeric_cols)
        stats["text_columns"] = len(text_cols)
        
        # 检测可能的主键
        for col in self.df.columns:
            if self.df[col].nunique() == len(self.df) and self.df[col].isna().sum() == 0:
                stats["potential_primary_key"] = col
                break
        
        return stats
    
    def get_dataframe(self) -> Optional[pd.DataFrame]:
        """获取解析后的 DataFrame"""
        return self.df


# 创建单例
data_parser = DataParser()

