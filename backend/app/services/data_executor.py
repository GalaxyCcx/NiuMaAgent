"""
数据查询执行服务
负责 SQL 生成和执行

使用 pandasql 直接执行 SQL，无需手动解析
"""
import re
import json
import pandas as pd
from pandasql import sqldf
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from ..models.session import Session, TableKnowledge, session_manager


def clean_html_and_urls(text: str) -> str:
    """
    彻底清理文本中的 HTML 标签和 URL
    
    处理：
    - 完整的 HTML 标签（包括嵌套）
    - 未闭合的 HTML 标签
    - 各种格式的 URL
    - HTML 实体
    """
    if not isinstance(text, str):
        return text
    
    # 1. 移除所有 HTML 标签（包括未闭合的）
    # 先处理完整的 <a> 标签
    text = re.sub(r'<a\s+[^>]*>.*?</a>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # 移除所有开标签
    text = re.sub(r'<[a-zA-Z][^>]*>', '', text)
    # 移除所有闭标签
    text = re.sub(r'</[a-zA-Z]+>', '', text)
    
    # 2. 移除各种格式的 URL
    # Steam linkfilter URLs
    text = re.sub(r'https?://steamcommunity\.com/linkfilter/\?url=[^\s<>"\']+', '', text)
    # 普通 URLs
    text = re.sub(r'https?://[^\s<>"\']+', '', text)
    # file:// URLs
    text = re.sub(r'file://[^\s<>"\']+', '', text)
    
    # 3. 移除 HTML 实体
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    
    # 4. 移除编码的引号
    text = text.replace('%22', '').replace('%27', '')
    
    # 5. 清理多余空格
    text = re.sub(r'\s{2,}', ' ', text)
    
    return text.strip()


def clean_dataframe_html(df: pd.DataFrame) -> pd.DataFrame:
    """
    清理 DataFrame 中所有字符串列的 HTML/URL
    """
    df = df.copy()
    
    for col in df.columns:
        if df[col].dtype == 'object':  # 字符串列
            df[col] = df[col].apply(lambda x: clean_html_and_urls(x) if isinstance(x, str) else x)
    
    return df


class DataExecutor:
    """数据执行器 - 使用 pandasql 执行 SQL 查询"""
    
    def __init__(self):
        self._dataframes: Dict[str, pd.DataFrame] = {}
    
    def load_table(self, table: TableKnowledge) -> Optional[pd.DataFrame]:
        """
        加载表数据到内存
        
        Args:
            table: 表知识库对象
        
        Returns:
            DataFrame 或 None
        """
        cache_key = f"{table.table_id}"
        
        # 检查缓存
        if cache_key in self._dataframes:
            return self._dataframes[cache_key]
        
        # 查找原始文件
        uploads_dir = session_manager.uploads_dir
        
        # 遍历所有 session 目录查找文件
        for session_dir in uploads_dir.iterdir():
            if session_dir.is_dir():
                file_path = session_dir / table.file_name
                if file_path.exists():
                    try:
                        df = pd.read_csv(file_path)
                        self._dataframes[cache_key] = df
                        return df
                    except Exception as e:
                        print(f"加载文件失败 {file_path}: {e}")
                        return None
        
        return None
    
    def load_session_tables(self, session: Session) -> Dict[str, pd.DataFrame]:
        """
        加载会话的所有表数据
        
        Args:
            session: 用户会话
        
        Returns:
            {表名: DataFrame} 字典
        """
        tables = {}
        
        for table in session.tables:
            df = self.load_table(table)
            if df is not None:
                tables[table.table_name] = df
        
        return tables
    
    def execute_sql(
        self, 
        session: Session, 
        sql: str,
        max_rows: int = 500
    ) -> Tuple[bool, Any, str]:
        """
        执行 SQL 查询
        
        Args:
            session: 用户会话
            sql: SQL 语句
            max_rows: 最大返回行数
        
        Returns:
            (成功, 结果数据, 消息)
        """
        try:
            # 加载所有表
            tables = self.load_session_tables(session)
            
            if not tables:
                return False, None, "没有可用的数据表，请先上传数据文件"
            
            # 清理 SQL
            sql = self._clean_sql(sql)
            
            # 安全检查
            if not self._validate_sql(sql):
                return False, None, "只支持 SELECT 查询语句"
            
            # 预验证（检查表名、列名）
            is_valid, validation_error, fix_suggestion = self._pre_validate_sql(sql, tables)
            if not is_valid:
                return False, {"validation_error": validation_error, "fix_suggestion": fix_suggestion}, f"SQL 预验证失败: {validation_error}"
            
            # 使用 pandasql 执行
            result = self._execute_with_pandasql(sql, tables, max_rows)
            
            return True, result, "查询成功"
            
        except Exception as e:
            error_msg = str(e)
            print(f"[SQL执行错误] {error_msg}")
            # 解析错误，生成修复建议
            fix_suggestion = self._generate_fix_suggestion(error_msg, tables)
            return False, {"error": error_msg, "fix_suggestion": fix_suggestion}, f"查询执行失败: {error_msg}"
    
    def _pre_validate_sql(
        self, 
        sql: str, 
        tables: Dict[str, pd.DataFrame]
    ) -> Tuple[bool, str, str]:
        """
        SQL 预验证：执行前检查表名、列名是否存在
        
        Returns:
            (是否有效, 错误信息, 修复建议)
        """
        sql_upper = sql.upper()
        available_tables = list(tables.keys())
        available_tables_lower = [t.lower() for t in available_tables]
        
        # 1. 检查禁止的复杂语法
        forbidden_patterns = [
            (r'\bIN\s*\(\s*SELECT\b', "禁止嵌套子查询 IN (SELECT ...)，请用 JOIN 代替"),
            (r'\bEXISTS\s*\(\s*SELECT\b', "禁止 EXISTS 子查询，请简化查询"),
            (r'\bFROM\s*\(\s*SELECT\b', "禁止 FROM 子查询，请直接查询表"),
            (r'\bUNION\b', "禁止 UNION，请分开查询"),
            (r'\bINTERSECT\b', "禁止 INTERSECT，请简化查询"),
            (r'\b(ROW_NUMBER|RANK|DENSE_RANK)\s*\(\s*\)\s*OVER\b', "禁止窗口函数，请用 GROUP BY + ORDER BY"),
        ]
        
        for pattern, error_msg in forbidden_patterns:
            if re.search(pattern, sql_upper):
                return False, error_msg, "请使用简单的 SELECT + WHERE + GROUP BY + ORDER BY 模式"
        
        # 2. 检查表名是否存在
        # 提取 FROM 和 JOIN 后的表名
        table_pattern = r'(?:FROM|JOIN)\s+[`"]?(\w+)[`"]?'
        referenced_tables = re.findall(table_pattern, sql, re.IGNORECASE)
        
        for table in referenced_tables:
            if table.lower() not in available_tables_lower:
                similar = self._find_similar_name(table, available_tables)
                suggestion = f"是否要查询 '{similar}'？" if similar else f"可用的表: {', '.join(available_tables)}"
                return False, f"表 '{table}' 不存在", suggestion
        
        # 3. 检查列名是否存在（对每个引用的表）
        for table_name in referenced_tables:
            # 找到匹配的表（不区分大小写）
            matched_table = None
            for t in available_tables:
                if t.lower() == table_name.lower():
                    matched_table = t
                    break
            
            if matched_table and matched_table in tables:
                df = tables[matched_table]
                available_columns = list(df.columns)
                
                # 提取 SQL 中引用的列名（简化版，只检查明显的列引用）
                # 包括：SELECT 字段、WHERE 条件、GROUP BY、ORDER BY
                column_patterns = [
                    rf'{table_name}\.`([^`]+)`',  # table.`column`
                    rf'{table_name}\."([^"]+)"',  # table."column"
                    rf'{table_name}\.(\w+)',       # table.column
                ]
                
                for pattern in column_patterns:
                    cols = re.findall(pattern, sql, re.IGNORECASE)
                    for col in cols:
                        if col not in available_columns:
                            similar = self._find_similar_name(col, available_columns)
                            suggestion = f"是否要使用 '{similar}'？" if similar else f"表 {matched_table} 的列: {available_columns[:10]}"
                            return False, f"表 '{matched_table}' 中不存在列 '{col}'", suggestion
        
        return True, "", ""
    
    def _find_similar_name(self, name: str, candidates: List[str]) -> Optional[str]:
        """查找最相似的名称（简单实现：前缀匹配或包含关系）"""
        name_lower = name.lower()
        
        for c in candidates:
            c_lower = c.lower()
            # 前缀匹配
            if c_lower.startswith(name_lower) or name_lower.startswith(c_lower):
                return c
            # 包含关系
            if name_lower in c_lower or c_lower in name_lower:
                return c
        
        return None
    
    def _generate_fix_suggestion(self, error_msg: str, tables: Dict[str, pd.DataFrame]) -> str:
        """根据错误信息生成修复建议"""
        error_lower = error_msg.lower()
        
        if "no such table" in error_lower:
            match = re.search(r'no such table: (\w+)', error_msg, re.IGNORECASE)
            if match:
                missing_table = match.group(1)
                similar = self._find_similar_name(missing_table, list(tables.keys()))
                if similar:
                    return f"表名错误，应该使用 '{similar}'"
                return f"可用的表: {', '.join(tables.keys())}"
        
        if "no such column" in error_lower:
            match = re.search(r'no such column: (\w+)', error_msg, re.IGNORECASE)
            if match:
                missing_col = match.group(1)
                # 在所有表中查找相似列名
                for table_name, df in tables.items():
                    similar = self._find_similar_name(missing_col, list(df.columns))
                    if similar:
                        return f"列名错误，在表 '{table_name}' 中应该使用 '{similar}'"
        
        if "unrecognized token" in error_lower:
            return "SQL 语法错误，请检查别名是否需要用引号包裹（数字开头的别名需要用引号）"
        
        if "syntax error" in error_lower:
            return "SQL 语法错误，请使用简单的 SELECT 语句"
        
        return "请简化 SQL 查询"
    
    def _clean_sql(self, sql: str) -> str:
        """清理 SQL 语句"""
        # 移除 markdown 代码块
        sql = re.sub(r'```sql\s*', '', sql)
        sql = re.sub(r'```\s*', '', sql)
        
        # 移除注释
        sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
        
        # 清理空白
        sql = sql.strip()
        
        # 移除结尾分号
        sql = sql.rstrip(';')
        
        return sql
    
    def _validate_sql(self, sql: str) -> bool:
        """验证 SQL 安全性"""
        sql_upper = sql.upper().strip()
        
        # 只允许 SELECT
        if not sql_upper.startswith('SELECT'):
            return False
        
        # 禁止危险操作
        forbidden = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 
                     'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC']
        for keyword in forbidden:
            if keyword in sql_upper:
                return False
        
        return True
    
    def _execute_with_pandasql(
        self, 
        sql: str, 
        tables: Dict[str, pd.DataFrame],
        max_rows: int
    ) -> Dict[str, Any]:
        """
        使用 pandasql 执行 SQL
        
        pandasql 使用 SQLite 语法，直接支持：
        - SELECT, FROM, WHERE, JOIN
        - GROUP BY, ORDER BY, LIMIT
        - 聚合函数: COUNT, SUM, AVG, MIN, MAX
        - 日期函数: strftime 等
        - 子查询、CASE WHEN 等
        """
        # 处理表名中的特殊字符（如日期中的 -）
        # pandasql 需要有效的 Python 标识符作为表名
        table_name_map = {}  # 原始名 -> 安全名
        safe_tables = {}
        
        for original_name, df in tables.items():
            # 将特殊字符替换为下划线
            safe_name = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', original_name)
            # 确保不以数字开头
            if safe_name and safe_name[0].isdigit():
                safe_name = 't_' + safe_name
            table_name_map[original_name] = safe_name
            safe_tables[safe_name] = df
        
        # 预处理 SQL：转换不兼容的语法
        sql = self._convert_sql_syntax(sql, tables)
        
        # 替换 SQL 中的表名为安全名
        for original_name, safe_name in table_name_map.items():
            if original_name != safe_name:
                # 替换 FROM 和 JOIN 后的表名
                sql = re.sub(
                    rf'\b{re.escape(original_name)}\b',
                    safe_name,
                    sql
                )
        
        # 构建本地变量字典供 pandasql 使用
        local_vars = safe_tables.copy()
        
        print(f"[SQL] 执行: {sql[:200]}...")
        print(f"[SQL] 可用表: {list(safe_tables.keys())}")
        
        # 执行 SQL（带超时机制）
        import concurrent.futures
        
        def run_sql():
            return sqldf(sql, local_vars)
        
        try:
            # 使用线程池执行，设置 30 秒超时
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_sql)
                try:
                    result_df = future.result(timeout=30)  # 30秒超时
                except concurrent.futures.TimeoutError:
                    raise ValueError("SQL 执行超时（30秒），请简化查询或减少数据量")
        except ValueError:
            raise
        except Exception as e:
            error_msg = str(e)
            # 提供更友好的错误信息
            if "no such table" in error_msg.lower():
                table_match = re.search(r'no such table: (\w+)', error_msg, re.IGNORECASE)
                if table_match:
                    missing_table = table_match.group(1)
                    available = ", ".join(tables.keys())
                    raise ValueError(f"表 '{missing_table}' 不存在。可用的表: {available}")
            elif "no such column" in error_msg.lower():
                col_match = re.search(r'no such column: (\w+)', error_msg, re.IGNORECASE)
                if col_match:
                    raise ValueError(f"列 '{col_match.group(1)}' 不存在")
            raise
        
        # 记录原始行数
        original_count = len(result_df)
        
        # 应用行数限制
        if len(result_df) > max_rows:
            result_df = result_df.head(max_rows)
        
        # 清理 HTML 和 URL（防止报告中出现超链接问题）
        result_df = clean_dataframe_html(result_df)
        
        print(f"[SQL] 结果: {len(result_df)} 行 (总共 {original_count} 行)")
        
        return {
            "columns": result_df.columns.tolist(),
            "data": result_df.to_dict(orient='records'),
            "row_count": len(result_df),
            "total_count": original_count,
            "truncated": original_count > max_rows
        }
    
    def _convert_sql_syntax(self, sql: str, tables: Dict[str, pd.DataFrame]) -> str:
        """
        转换 SQL 语法，使其兼容 SQLite（pandasql 底层使用 SQLite）
        
        PostgreSQL/MySQL 特有语法 → SQLite 语法
        """
        # 1. 处理标识符引号
        # SQLite 使用双引号包裹标识符，MySQL 使用反引号
        # 将反引号包裹的标识符转换为双引号（保留包含特殊字符的标识符）
        def convert_backtick_identifier(match):
            identifier = match.group(1)
            # 如果标识符只包含字母、数字、下划线，可以不加引号
            if re.match(r'^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*$', identifier):
                return identifier
            # 否则使用双引号包裹（SQLite 语法）
            return f'"{identifier}"'
        
        sql = re.sub(r'`([^`]+)`', convert_backtick_identifier, sql)
        
        # 对于纯字母数字的双引号标识符，可以移除引号
        # 但保留包含特殊字符的标识符的引号
        def simplify_quoted_identifier(match):
            identifier = match.group(1)
            if re.match(r'^[a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*$', identifier):
                return identifier
            return f'"{identifier}"'
        
        sql = re.sub(r'"([^"]+)"', simplify_quoted_identifier, sql)
        
        # 1.5 处理 AS 后面以数字开头的别名（SQLite 要求加引号）
        # 例如: AS 24K本地售价 -> AS "24K本地售价"
        def quote_numeric_alias(match):
            keyword = match.group(1)  # AS
            alias = match.group(2)     # 别名
            # 如果别名以数字开头，需要用双引号包裹
            if alias and alias[0].isdigit():
                return f'{keyword} "{alias}"'
            return match.group(0)
        
        # 匹配 AS 后面跟着以数字开头的标识符（不在引号内）
        sql = re.sub(r'\b(AS)\s+(\d+[a-zA-Z0-9_\u4e00-\u9fff]*)\b', quote_numeric_alias, sql, flags=re.IGNORECASE)
        
        # 2. 转换 EXTRACT(YEAR FROM date) → strftime('%Y', date)
        # PostgreSQL: EXTRACT(YEAR FROM release_date)
        # SQLite: strftime('%Y', release_date)
        def replace_extract(match):
            part = match.group(1).upper()
            field = match.group(2)
            # 移除类型转换 ::date, ::timestamp 等
            field = re.sub(r'::\w+', '', field).strip()
            
            format_map = {
                'YEAR': '%Y',
                'MONTH': '%m',
                'DAY': '%d',
                'HOUR': '%H',
                'MINUTE': '%M',
                'SECOND': '%S',
            }
            fmt = format_map.get(part, '%Y')
            return f"strftime('{fmt}', {field})"
        
        sql = re.sub(
            r'EXTRACT\s*\(\s*(\w+)\s+FROM\s+([^)]+)\)',
            replace_extract,
            sql,
            flags=re.IGNORECASE
        )
        
        # 3. 移除 PostgreSQL 类型转换 ::type
        sql = re.sub(r'::\w+', '', sql)
        
        # 4. 转换 MySQL 的 STR_TO_DATE -> 直接使用字段（SQLite 可直接比较日期字符串）
        sql = re.sub(
            r"STR_TO_DATE\s*\(\s*([^,]+),\s*'[^']+'\s*\)",
            r"\1",
            sql, flags=re.IGNORECASE
        )
        
        # 5. 转换 MySQL 的 DATE_FORMAT -> strftime
        def replace_date_format(match):
            field = match.group(1).strip()
            mysql_fmt = match.group(2)
            # MySQL -> SQLite 格式映射
            fmt_map = {
                '%Y': '%Y', '%y': '%Y',
                '%m': '%m', '%d': '%d',
                '%Y-%m': '%Y-%m',
                '%Y-%m-%d': '%Y-%m-%d',
                '%Y%m': '%Y%m',
            }
            sqlite_fmt = fmt_map.get(mysql_fmt, '%Y-%m-%d')
            return f"strftime('{sqlite_fmt}', {field})"
        
        sql = re.sub(
            r"DATE_FORMAT\s*\(\s*([^,]+),\s*'([^']+)'\s*\)",
            replace_date_format,
            sql, flags=re.IGNORECASE
        )
        
        # 6. 转换 MySQL 的 YEAR(field) -> strftime('%Y', field)
        sql = re.sub(
            r"\bYEAR\s*\(\s*([^)]+)\s*\)",
            r"strftime('%Y', \1)",
            sql, flags=re.IGNORECASE
        )
        
        # 7. 转换 MySQL 的 MONTH(field) -> strftime('%m', field)
        sql = re.sub(
            r"\bMONTH\s*\(\s*([^)]+)\s*\)",
            r"strftime('%m', \1)",
            sql, flags=re.IGNORECASE
        )
        
        # 8. 转换 MySQL 的 DAY(field) -> strftime('%d', field)
        sql = re.sub(
            r"\bDAY\s*\(\s*([^)]+)\s*\)",
            r"strftime('%d', \1)",
            sql, flags=re.IGNORECASE
        )
        
        # 9. 转换 ILIKE → LIKE（SQLite 的 LIKE 默认不区分大小写）
        sql = re.sub(r'\bILIKE\b', 'LIKE', sql, flags=re.IGNORECASE)
        
        # 10. 修复 MongoDB 风格的日期范围语法（LLM 常见错误）
        # 错误格式: 日期 = {'$gte': '2025-01-01', '$lte': '2025-12-31'}
        # 正确格式: 日期 BETWEEN '2025-01-01' AND '2025-12-31'
        def fix_mongodb_syntax(match):
            field = match.group(1).strip()
            content = match.group(2)
            
            # 尝试提取日期范围
            gte_match = re.search(r"\'\$gte\'\s*:\s*\'([^\']+)\'", content)
            lte_match = re.search(r"\'\$lte\'\s*:\s*\'([^\']+)\'", content)
            between_match = re.search(r"\'\$between\'\s*:\s*\[\'([^\']+)\',\s*\'([^\']+)\'\]", content)
            
            if gte_match and lte_match:
                start_date = gte_match.group(1)
                end_date = lte_match.group(1)
                return f"{field} BETWEEN '{start_date}' AND '{end_date}'"
            elif between_match:
                start_date = between_match.group(1)
                end_date = between_match.group(2)
                return f"{field} BETWEEN '{start_date}' AND '{end_date}'"
            
            # 无法解析，返回原文
            return match.group(0)
        
        # 匹配: field = {...}
        sql = re.sub(
            r'(\w+)\s*=\s*(\{[^\}]+\})',
            fix_mongodb_syntax,
            sql
        )
        
        # 11. 修复错误的 BETWEEN 字符串格式
        # 错误: 日期 = 'BETWEEN '2025-01-01' AND '2025-12-31''
        # 正确: 日期 BETWEEN '2025-01-01' AND '2025-12-31'
        sql = re.sub(
            r"(\w+)\s*=\s*'BETWEEN\s*'([^']+)'\s*AND\s*'([^']+)''",
            r"\1 BETWEEN '\2' AND '\3'",
            sql, flags=re.IGNORECASE
        )
        
        # 12. 移除不支持的正则函数（SQLite 不支持 REGEXP_SUBSTR 等）
        # REGEXP_SUBSTR(field, pattern) -> field（简单返回原字段）
        sql = re.sub(
            r"REGEXP_SUBSTR\s*\(\s*([^,]+),\s*'[^']*'\s*\)",
            r"\1",
            sql, flags=re.IGNORECASE
        )
        
        # 11. 移除其他不支持的正则函数
        sql = re.sub(
            r"REGEXP_REPLACE\s*\(\s*([^,]+),\s*'[^']*',\s*'[^']*'\s*\)",
            r"\1",
            sql, flags=re.IGNORECASE
        )
        
        # 12. 转换 || 字符串连接（SQLite 支持，但确保空格正确）
        # 无需转换
        
        # 6. 转换 LIMIT x OFFSET y → LIMIT x OFFSET y（语法相同）
        # 无需转换
        
        # 7. 确保表名使用正确的大小写（pandasql 区分大小写）
        for table_name in tables.keys():
            # 替换 FROM table_name（不区分大小写匹配，替换为正确大小写）
            sql = re.sub(
                rf'\bFROM\s+{table_name}\b',
                f'FROM {table_name}',
                sql,
                flags=re.IGNORECASE
            )
            sql = re.sub(
                rf'\bJOIN\s+{table_name}\b',
                f'JOIN {table_name}',
                sql,
                flags=re.IGNORECASE
            )
        
        return sql
    
    def get_table_preview(
        self, 
        session: Session, 
        table_name: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        获取表预览数据
        
        Args:
            session: 用户会话
            table_name: 表名
            limit: 返回行数
        
        Returns:
            预览数据
        """
        tables = self.load_session_tables(session)
        
        if table_name not in tables:
            return {"error": f"表 '{table_name}' 不存在"}
        
        df = tables[table_name]
        
        return {
            "columns": df.columns.tolist(),
            "data": df.head(limit).to_dict(orient='records'),
            "row_count": limit,
            "total_count": len(df)
        }
    
    def get_column_stats(
        self, 
        session: Session, 
        table_name: str,
        column_name: str
    ) -> Dict[str, Any]:
        """
        获取列统计信息
        
        Args:
            session: 用户会话
            table_name: 表名
            column_name: 列名
        
        Returns:
            列统计信息
        """
        tables = self.load_session_tables(session)
        
        if table_name not in tables:
            return {"error": f"表 '{table_name}' 不存在"}
        
        df = tables[table_name]
        
        if column_name not in df.columns:
            return {"error": f"列 '{column_name}' 不存在"}
        
        col = df[column_name]
        
        stats = {
            "column_name": column_name,
            "dtype": str(col.dtype),
            "count": int(col.count()),
            "null_count": int(col.isnull().sum()),
            "unique_count": int(col.nunique()),
        }
        
        # 数值类型添加统计
        if pd.api.types.is_numeric_dtype(col):
            stats.update({
                "min": float(col.min()) if not pd.isna(col.min()) else None,
                "max": float(col.max()) if not pd.isna(col.max()) else None,
                "mean": float(col.mean()) if not pd.isna(col.mean()) else None,
                "std": float(col.std()) if not pd.isna(col.std()) else None,
            })
        
        # 添加 top 值
        value_counts = col.value_counts().head(10)
        stats["top_values"] = [
            {"value": str(v), "count": int(c)}
            for v, c in value_counts.items()
        ]
        
        return stats


# 创建单例
data_executor = DataExecutor()
