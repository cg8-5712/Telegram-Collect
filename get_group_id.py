"""
获取 Telegram 群组 ID 的辅助脚本
使用已保存的 session，无需重复登录
"""
import asyncio
import sys
from pathlib import Path
from telethon import TelegramClient

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config import load_config


async def main():
    """主函数"""
    print("=" * 60)
    print("Telegram 群组 ID 获取工具")
    print("=" * 60)
    print()

    try:
        # 从 config.yaml 加载配置
        print("正在加载配置文件...")
        config = load_config("config.yaml")

        monitor_account = config['monitor_account']
        api_id = monitor_account['api_id']
        api_hash = monitor_account['api_hash']
        session_file = monitor_account.get('session_file', 'sessions/monitor.session')

        print(f"使用 session: {session_file}")
        print()
        print("正在连接 Telegram...")

        # 创建客户端（使用已保存的 session）
        client = TelegramClient(session_file, api_id, api_hash)

        await client.connect()

        # 检查是否已登录
        if not await client.is_user_authorized():
            print()
            print("⚠️  未找到有效的登录 session")
            print("请先运行 'python start.py' 或 'python main.py' 完成登录")
            print()
            await client.disconnect()
            return

        # 获取当前用户信息
        me = await client.get_me()
        print(f"✅ 已登录账号: {me.first_name} (@{me.username})")
        print()
        print("=" * 60)
        print("你的群组和频道列表：")
        print("=" * 60)
        print()

        # 获取所有对话
        count = 0
        async for dialog in client.iter_dialogs():
            # 只显示群组和频道
            if dialog.is_group or dialog.is_channel:
                count += 1
                print(f"[{count}] 名称: {dialog.name}")
                print(f"    ID: {dialog.id}")
                print(f"    类型: {'群组' if dialog.is_group else '频道'}")
                print("-" * 60)

        if count == 0:
            print("未找到任何群组或频道")
        else:
            print()
            print(f"共找到 {count} 个群组/频道")
            print()
            print("💡 使用方法：")
            print("   将上面的 ID 复制到 config.yaml 的 monitor_groups 中")
            print()
            print("   示例：")
            print("   monitor_groups:")
            print("     - group_id: -1001234567890  # 复制上面的 ID")
            print("       group_name: \"群组名称\"")
            print("       enabled: true")

        print()

    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        print("请确保 config.yaml 文件存在")
    except Exception as e:
        print(f"❌ 错误: {e}")
    finally:
        if 'client' in locals():
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
