#!/usr/bin/env python3
"""
统一启动脚本 - 同时运行监控服务和 Web 管理界面
"""
import asyncio
import sys
import threading
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from src.core.monitor import TelegramMonitor
from src.utils.logger import setup_logger
from src.utils.config import load_config
from web_app import run_web_app


def run_web_in_thread():
    """在独立线程中运行 Web 应用"""
    logger = setup_logger("WebApp")
    logger.info("启动 Web 管理界面...")
    run_web_app(host='0.0.0.0', port=5000, debug=False)


async def run_monitor():
    """运行监控服务"""
    try:
        # 加载配置
        config = load_config("config.yaml")

        # 从配置中获取日志设置
        log_config = config.get('logging', {})
        log_level = log_config.get('level', 'INFO')
        log_file = log_config.get('file', 'logs/monitor.log')
        max_size = log_config.get('max_size', 10485760)
        backup_count = log_config.get('backup_count', 5)

        # 设置日志
        logger = setup_logger(
            name="TelegramMonitor",
            log_file=log_file,
            level=log_level,
            max_bytes=max_size,
            backup_count=backup_count
        )

        logger.info("=" * 60)
        logger.info("Telegram 群组关键词监控系统启动")
        logger.info("=" * 60)
        logger.info(f"日志级别: {log_level}")

        # 创建监控实例
        logger.info("初始化监控系统...")
        monitor = TelegramMonitor(config, config_file="config.yaml")

        # 启动监控
        logger.info("启动监控服务...")
        await monitor.start()

    except KeyboardInterrupt:
        logger.info("\n收到停止信号，正在关闭...")
    except Exception as e:
        logger.error(f"系统错误: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("监控系统已停止")


def main():
    """主函数"""
    print("=" * 60)
    print("Telegram 监控系统 - 统一启动")
    print("=" * 60)
    print()
    print("启动服务:")
    print("  - Web 管理界面: http://0.0.0.0:5000")
    print("  - Telegram 监控服务")
    print()
    print("=" * 60)
    print()

    # 在独立线程中启动 Web 服务
    web_thread = threading.Thread(target=run_web_in_thread, daemon=True)
    web_thread.start()

    # 在主线程中运行监控服务（需要交互式输入）
    asyncio.run(run_monitor())


if __name__ == "__main__":
    main()
