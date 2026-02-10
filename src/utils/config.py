"""
配置文件加载工具
"""
import yaml
from pathlib import Path
from typing import Dict, Any


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典
    """
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 验证必需的配置项
    _validate_config(config)

    return config


def _validate_config(config: Dict[str, Any]) -> None:
    """
    验证配置文件的必需项

    Args:
        config: 配置字典
    """
    required_keys = [
        'monitor_account',
        'notify_target',
        'monitor_groups',
        'keywords'
    ]

    for key in required_keys:
        if key not in config:
            raise ValueError(f"配置文件缺少必需项: {key}")

    # 验证账号B配置
    monitor_account = config['monitor_account']
    if 'phone' not in monitor_account:
        raise ValueError("monitor_account 缺少 phone 配置")
    if 'api_id' not in monitor_account:
        raise ValueError("monitor_account 缺少 api_id 配置")
    if 'api_hash' not in monitor_account:
        raise ValueError("monitor_account 缺少 api_hash 配置")

    # 验证账号A配置
    notify_target = config['notify_target']
    if 'username' not in notify_target and 'user_id' not in notify_target:
        raise ValueError("notify_target 必须配置 username 或 user_id")

    # 验证群组配置
    if not config['monitor_groups']:
        raise ValueError("monitor_groups 不能为空")

    # 验证关键词配置
    keywords = config['keywords']
    if not any([keywords.get('exact'), keywords.get('contains'), keywords.get('regex')]):
        raise ValueError("keywords 至少需要配置一种匹配方式")
