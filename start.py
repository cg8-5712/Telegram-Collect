#!/usr/bin/env python3
"""
统一启动脚本 - 同时运行多账号监控服务和 Web 管理界面
"""
import asyncio
import logging
import sys
import threading
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from src.core.monitor import TelegramMonitor, monitor_registry
from src.core.statistics import StatisticsDB
from src.utils.logger import setup_logger
from src.utils.config import load_config
from web_app import run_web_app


def run_web_in_thread():
    """在独立线程中运行 Web 应用"""
    logger = setup_logger("WebApp")
    logger.info("启动 Web 管理界面...")
    run_web_app(host='0.0.0.0', port=5000, debug=False)


async def run_single_monitor(config, account, stats_db, logger):
    """运行单个账号的监控服务"""
    name = account.get('name', account['phone'])
    try:
        monitor = TelegramMonitor(
            config=config,
            account=account,
            config_file="config.yaml",
            stats_db=stats_db,
        )
        logger.info(f"[{name}] 启动监控服务...")
        await monitor.start()
    except Exception as e:
        logger.error(f"[{name}] 监控异常退出: {e}", exc_info=True)
        # 标记为离线
        if name in monitor_registry:
            monitor_registry[name]['online'] = False


async def run_monitors():
    """运行所有账号的监控服务"""
    logger = logging.getLogger("TelegramMonitor")
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
        logger.info("Telegram 群组关键词监控系统启动（多账号模式）")
        logger.info("=" * 60)
        logger.info(f"日志级别: {log_level}")

        # 解析账号列表（兼容旧版 monitor_account 单账号格式）
        if 'monitor_accounts' in config:
            accounts = config['monitor_accounts']
        elif 'monitor_account' in config:
            # 旧版单账号，转为列表
            acc = config['monitor_account']
            acc.setdefault('name', '默认账号')
            acc.setdefault('enabled', True)
            accounts = [acc]
        else:
            logger.error("配置文件中未找到 monitor_accounts 或 monitor_account")
            sys.exit(1)

        # 过滤启用的账号
        enabled_accounts = [a for a in accounts if a.get('enabled', True)]
        logger.info(f"共 {len(accounts)} 个账号，启用 {len(enabled_accounts)} 个")

        if not enabled_accounts:
            logger.warning("没有启用的账号，退出")
            return

        # 共享统计数据库
        stats_db = StatisticsDB()

        # 并发启动所有账号
        tasks = []
        for account in enabled_accounts:
            name = account.get('name', account['phone'])
            logger.info(f"初始化账号: {name} ({account['phone']})")
            task = asyncio.create_task(
                run_single_monitor(config, account, stats_db, logger)
            )
            tasks.append(task)

        # 等待所有任务（任一退出不影响其他）
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                name = enabled_accounts[i].get('name', enabled_accounts[i]['phone'])
                logger.error(f"[{name}] 退出异常: {result}")

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
    print("Telegram 监控系统 - 多账号统一启动")
    print("=" * 60)
    print()
    print("启动服务:")
    print("  - Web 管理界面: http://0.0.0.0:5000")
    print("  - Telegram 多账号监控服务")
    print()
    print("=" * 60)
    print()

    # 在独立线程中启动 Web 服务
    web_thread = threading.Thread(target=run_web_in_thread, daemon=True)
    web_thread.start()

    # 在主线程中运行多账号监控服务
    asyncio.run(run_monitors())


if __name__ == "__main__":
    main()
