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

        # 红包领取记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS red_packet_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                total_amount REAL,
                total_count INTEGER,
                expression TEXT,
                answer REAL,
                clicked_button TEXT,
                delay_seconds REAL,
                success INTEGER DEFAULT 0,
                amount_received REAL,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_keyword_hits_keyword ON keyword_hits(keyword)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_red_packet_created_at ON red_packet_records(created_at)")

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

    # ==================== 红包记录相关方法 ====================

    def record_red_packet(self, group_id, group_name, total_amount=None, total_count=None,
                          expression=None, answer=None, clicked_button=None, delay_seconds=None,
                          success=False, amount_received=None, error_message=None):
        """记录红包领取"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO red_packet_records
            (group_id, group_name, total_amount, total_count, expression, answer,
             clicked_button, delay_seconds, success, amount_received, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (group_id, group_name, total_amount, total_count, expression, answer,
              clicked_button, delay_seconds, 1 if success else 0, amount_received, error_message))

        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return record_id

    def update_red_packet_result(self, record_id, amount_received):
        """更新红包领取结果金额"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE red_packet_records
            SET amount_received = ?, success = 1
            WHERE id = ?
        """, (amount_received, record_id))

        conn.commit()
        conn.close()

    def get_red_packet_stats(self, days=7):
        """获取红包统计概览"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 总计
        cursor.execute("""
            SELECT COUNT(*), SUM(CASE WHEN success=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN success=1 THEN amount_received ELSE 0 END)
            FROM red_packet_records
            WHERE created_at >= datetime('now', '-' || ? || ' days')
        """, (days,))
        row = cursor.fetchone()
        total = row[0] or 0
        success_count = row[1] or 0
        total_received = row[2] or 0

        # 按日统计
        cursor.execute("""
            SELECT DATE(created_at) as date,
                   COUNT(*) as attempts,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
                   SUM(CASE WHEN success=1 THEN amount_received ELSE 0 END) as received
            FROM red_packet_records
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (days,))
        daily = cursor.fetchall()

        conn.close()

        return {
            'total_attempts': total,
            'success_count': success_count,
            'total_received': round(total_received, 2) if total_received else 0,
            'success_rate': round(success_count / total * 100, 1) if total > 0 else 0,
            'daily_stats': [
                {
                    'date': r[0],
                    'attempts': r[1],
                    'successes': r[2] or 0,
                    'received': round(r[3], 2) if r[3] else 0
                }
                for r in daily
            ]
        }

    def get_red_packet_history(self, limit=50, offset=0, group_id=None, start_date=None, end_date=None):
        """获取红包领取历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM red_packet_records WHERE 1=1"
        params = []

        if group_id:
            query += " AND group_id = ?"
            params.append(group_id)
        if start_date:
            query += " AND created_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND created_at <= ?"
            params.append(end_date)

        # 总数
        count_query = query.replace("SELECT *", "SELECT COUNT(*)")
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()

        return {
            'total': total,
            'records': [
                {
                    'id': row[0],
                    'group_id': row[1],
                    'group_name': row[2],
                    'total_amount': row[3],
                    'total_count': row[4],
                    'expression': row[5],
                    'answer': row[6],
                    'clicked_button': row[7],
                    'delay_seconds': row[8],
                    'success': bool(row[9]),
                    'amount_received': row[10],
                    'error_message': row[11],
                    'created_at': row[12]
                }
                for row in results
            ]
        }

    def get_red_packet_calendar(self, year, month):
        """
        获取指定月份的红包日历数据

        Args:
            year: 年份
            month: 月份

        Returns:
            dict: {date_str: {attempts, successes, total_received}}
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"

        cursor.execute("""
            SELECT
                DATE(created_at) as day,
                COUNT(*) as attempts,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                COALESCE(SUM(amount_received), 0) as total_received
            FROM red_packet_records
            WHERE created_at >= ? AND created_at < ?
            GROUP BY DATE(created_at)
            ORDER BY day
        """, (start_date, end_date))

        results = cursor.fetchall()
        conn.close()

        calendar_data = {}
        for row in results:
            calendar_data[row[0]] = {
                'attempts': row[1],
                'successes': row[2],
                'total_received': row[3]
            }

        return calendar_data