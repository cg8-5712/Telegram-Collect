#!/usr/bin/env python3
"""
数据库迁移脚本 - 为红包记录表添加 account_name 字段
"""
import sqlite3
import yaml
from pathlib import Path


def migrate_database():
    """执行数据库迁移"""
    db_path = "data/statistics.db"

    if not Path(db_path).exists():
        print(f"数据库文件不存在: {db_path}")
        print("无需迁移")
        return

    # 读取配置获取第一个账号名称
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 获取第一个账号名称
        if 'monitor_accounts' in config and config['monitor_accounts']:
            first_account = config['monitor_accounts'][0].get('name', '主账号')
        else:
            first_account = '主账号'

        print(f"将使用账号名称: {first_account}")
    except Exception as e:
        print(f"读取配置失败: {e}")
        first_account = '主账号'
        print(f"使用默认账号名称: {first_account}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查 account_name 列是否已存在
    cursor.execute("PRAGMA table_info(red_packet_records)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'account_name' in columns:
        print("✓ account_name 字段已存在，无需迁移")
        conn.close()
        return

    print("开始迁移数据库...")

    try:
        # 添加 account_name 列
        cursor.execute("""
            ALTER TABLE red_packet_records
            ADD COLUMN account_name TEXT
        """)
        print("✓ 已添加 account_name 字段")

        # 将所有现有记录的 account_name 设置为第一个账号
        cursor.execute("""
            UPDATE red_packet_records
            SET account_name = ?
            WHERE account_name IS NULL
        """, (first_account,))

        updated_count = cursor.rowcount
        print(f"✓ 已更新 {updated_count} 条记录，设置为账号: {first_account}")

        conn.commit()
        print("✓ 数据库迁移完成！")

    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移工具")
    print("=" * 60)
    migrate_database()
    print("=" * 60)
