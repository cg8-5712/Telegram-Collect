"""
Telegram 群组关键词监控系统
主程序入口
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from src.core.monitor import TelegramMonitor
from src.utils.logger import setup_logger
from src.utils.config import load_config


async def main():
    """主函数"""
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
        logger.info("系统已停止")


if __name__ == "__main__":
    # 运行主程序
    asyncio.run(main())
