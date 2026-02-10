"""
数据统计模块 - 数据库模型
"""
import sqlite3
from datetime import datetime
from pathlib import Path


class StatisticsDB:
    """统计数据库"""

    def __init__(self, db_path="data/statistics.db"):
        """初始化数据库"""
        self.db_path = db_path

        # 创建数据目录
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 消息记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                message_text TEXT,
                sender_id INTEGER,
                sender_name TEXT,
                matched_keyword TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 关键词命中统计表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS keyword_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                hit_count INTEGER DEFAULT 1,
                last_hit_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 群组活跃度统计表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                message_count INTEGER DEFAULT 1,
                keyword_hit_count INTEGER DEFAULT 0,
                last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id)
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_keyword_hits_keyword ON keyword_hits(keyword)")

        conn.commit()
        conn.close()

    def record_message(self, group_id, group_name, message_text, sender_id=None, sender_name=None, matched_keyword=None):
        """记录消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO messages (group_id, group_name, message_text, sender_id, sender_name, matched_keyword)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (group_id, group_name, message_text, sender_id, sender_name, matched_keyword))

        # 如果有匹配的关键词，更新关键词统计
        if matched_keyword:
            cursor.execute("""
                INSERT INTO keyword_hits (keyword, hit_count, last_hit_at)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(keyword) DO UPDATE SET
                    hit_count = hit_count + 1,
                    last_hit_at = CURRENT_TIMESTAMP
            """, (matched_keyword,))

        # 更新群组活跃度
        cursor.execute("""
            INSERT INTO group_activity (group_id, group_name, message_count, keyword_hit_count, last_activity_at)
            VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id) DO UPDATE SET
                message_count = message_count + 1,
                keyword_hit_count = keyword_hit_count + ?,
                last_activity_at = CURRENT_TIMESTAMP
        """, (group_id, group_name, 1 if matched_keyword else 0, 1 if matched_keyword else 0))

        conn.commit()
        conn.close()

    def get_message_stats(self, days=7):
        """获取消息统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 总消息数
        cursor.execute("""
            SELECT COUNT(*) FROM messages
            WHERE created_at >= datetime('now', '-' || ? || ' days')
        """, (days,))
        total_messages = cursor.fetchone()[0]

        # 关键词命中数
        cursor.execute("""
            SELECT COUNT(*) FROM messages
            WHERE matched_keyword IS NOT NULL
            AND created_at >= datetime('now', '-' || ? || ' days')
        """, (days,))
        keyword_hits = cursor.fetchone()[0]

        # 按日期统计
        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM messages
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (days,))
        daily_stats = cursor.fetchall()

        conn.close()

        return {
            'total_messages': total_messages,
            'keyword_hits': keyword_hits,
            'daily_stats': [{'date': row[0], 'count': row[1]} for row in daily_stats]
        }

    def get_keyword_stats(self, limit=10):
        """获取关键词统计（Top N）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT keyword, hit_count, last_hit_at
            FROM keyword_hits
            ORDER BY hit_count DESC
            LIMIT ?
        """, (limit,))

        results = cursor.fetchall()
        conn.close()

        return [
            {
                'keyword': row[0],
                'hit_count': row[1],
                'last_hit_at': row[2]
            }
            for row in results
        ]

    def get_group_stats(self, limit=10):
        """获取群组活跃度统计（Top N）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT group_id, group_name, message_count, keyword_hit_count, last_activity_at
            FROM group_activity
            ORDER BY message_count DESC
            LIMIT ?
        """, (limit,))

        results = cursor.fetchall()
        conn.close()

        return [
            {
                'group_id': row[0],
                'group_name': row[1],
                'message_count': row[2],
                'keyword_hit_count': row[3],
                'last_activity_at': row[4]
            }
            for row in results
        ]

    def get_history(self, limit=50, offset=0, group_id=None, keyword=None, start_date=None, end_date=None):
        """获取历史记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM messages WHERE 1=1"
        params = []

        if group_id:
            query += " AND group_id = ?"
            params.append(group_id)

        if keyword:
            query += " AND matched_keyword = ?"
            params.append(keyword)

        if start_date:
            query += " AND created_at >= ?"
            params.append(start_date)

        if end_date:
            query += " AND created_at <= ?"
            params.append(end_date)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        results = cursor.fetchall()

        # 获取总数
        count_query = "SELECT COUNT(*) FROM messages WHERE 1=1"
        count_params = []

        if group_id:
            count_query += " AND group_id = ?"
            count_params.append(group_id)

        if keyword:
            count_query += " AND matched_keyword = ?"
            count_params.append(keyword)

        if start_date:
            count_query += " AND created_at >= ?"
            count_params.append(start_date)

        if end_date:
            count_query += " AND created_at <= ?"
            count_params.append(end_date)

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()[0]

        conn.close()

        return {
            'total': total,
            'records': [
                {
                    'id': row[0],
                    'group_id': row[1],
                    'group_name': row[2],
                    'message_text': row[3],
                    'sender_id': row[4],
                    'sender_name': row[5],
                    'matched_keyword': row[6],
                    'created_at': row[7]
                }
                for row in results
            ]
        }

    def export_data(self, start_date=None, end_date=None):
        """导出数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM messages WHERE 1=1"
        params = []

        if start_date:
            query += " AND created_at >= ?"
            params.append(start_date)

        if end_date:
            query += " AND created_at <= ?"
            params.append(end_date)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()

        return [
            {
                'id': row[0],
                'group_id': row[1],
                'group_name': row[2],
                'message_text': row[3],
                'sender_id': row[4],
                'sender_name': row[5],
                'matched_keyword': row[6],
                'created_at': row[7]
            }
            for row in results
        ]
