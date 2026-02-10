"""
配置热重载管理器
监控 config.yaml 文件变化，自动重新加载配置
"""
import os
import time
import yaml
import logging
from pathlib import Path
from typing import Callable, Dict, Any


class ConfigReloader:
    """配置文件热重载器"""

    def __init__(self, config_file: str, check_interval: int = 5):
        """
        初始化配置重载器

        Args:
            config_file: 配置文件路径
            check_interval: 检查间隔（秒）
        """
        self.config_file = config_file
        self.check_interval = check_interval
        self.last_mtime = 0
        self.callbacks = []
        self.logger = logging.getLogger("ConfigReloader")

        # 初始化时记录文件修改时间
        if os.path.exists(config_file):
            self.last_mtime = os.path.getmtime(config_file)

    def register_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """
        注册配置更新回调函数

        Args:
            callback: 回调函数，接收新配置作为参数
        """
        self.callbacks.append(callback)

    def check_and_reload(self) -> bool:
        """
        检查配置文件是否修改，如果修改则重新加载

        Returns:
            是否重新加载了配置
        """
        try:
            if not os.path.exists(self.config_file):
                return False

            current_mtime = os.path.getmtime(self.config_file)

            # 文件未修改
            if current_mtime <= self.last_mtime:
                return False

            # 文件已修改，重新加载
            self.logger.info(f"检测到配置文件变化，重新加载: {self.config_file}")

            with open(self.config_file, 'r', encoding='utf-8') as f:
                new_config = yaml.safe_load(f)

            # 更新修改时间
            self.last_mtime = current_mtime

            # 调用所有回调函数
            for callback in self.callbacks:
                try:
                    callback(new_config)
                except Exception as e:
                    self.logger.error(f"配置更新回调失败: {e}", exc_info=True)

            self.logger.info("配置重新加载成功")
            return True

        except Exception as e:
            self.logger.error(f"配置重新加载失败: {e}", exc_info=True)
            return False

    def get_last_modified_time(self) -> float:
        """获取配置文件最后修改时间"""
        if os.path.exists(self.config_file):
            return os.path.getmtime(self.config_file)
        return 0
