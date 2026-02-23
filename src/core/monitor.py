"""
Telegram 监控核心模块
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from telethon import TelegramClient, events
from telethon.tl.types import User, Channel
from telethon.errors import SessionPasswordNeededError

from .keyword_matcher import KeywordMatcher
from .statistics import StatisticsDB
from .red_packet import RedPacketHandler
from ..utils.config_reloader import ConfigReloader


# 全局账号状态注册表，供 WebUI 查询
# 结构: { account_name: { phone, online, username, groups_count, started_at } }
monitor_registry: Dict[str, Dict[str, Any]] = {}


class TelegramMonitor:
    """Telegram 监控器（单账号实例）"""

    def __init__(self, config: Dict[str, Any], account: Dict[str, Any],
                 config_file: str = "config.yaml", enable_statistics=True,
                 stats_db: Optional[StatisticsDB] = None):
        """
        初始化监控器

        Args:
            config: 完整配置字典
            account: 单个账号配置 {phone, api_id, api_hash, session_file, name}
            config_file: 配置文件路径
            enable_statistics: 是否启用统计功能
            stats_db: 共享的统计数据库实例（多账号共享同一个DB）
        """
        self.config = config
        self.config_file = config_file
        self.logger = logging.getLogger("TelegramMonitor")

        # 账号配置
        self.account_name = account.get('name', account['phone'])
        self.phone = account['phone']
        self.api_id = account['api_id']
        self.api_hash = account['api_hash']
        session_file = account.get('session_file', f'sessions/monitor-{self.phone}.session')

        # 创建 session 目录
        Path(session_file).parent.mkdir(parents=True, exist_ok=True)

        # 代理配置 (支持字符串或dict格式)
        proxy_config = account.get('proxy')
        if isinstance(proxy_config, str):
            import re
            m = re.match(r'^(socks5|socks4|http)://([^:]+):(\d+)$', proxy_config)
            if m:
                proxy_config = {'enabled': True, 'type': m.group(1), 'host': m.group(2), 'port': int(m.group(3))}
            else:
                proxy_config = None
        proxy = None
        if proxy_config and isinstance(proxy_config, dict) and proxy_config.get('enabled', True):
            import socks
            proxy_type_map = {
                'socks5': socks.SOCKS5,
                'socks4': socks.SOCKS4,
                'http': socks.HTTP,
            }
            ptype = proxy_type_map.get(proxy_config.get('type', 'socks5').lower(), socks.SOCKS5)
            proxy = (
                ptype,
                proxy_config.get('host', '127.0.0.1'),
                int(proxy_config.get('port', 7897)),
                True,  # rdns
                proxy_config.get('username'),
                proxy_config.get('password'),
            )
            self.logger.info(f"[{self.account_name}] 使用代理: {proxy_config.get('type','socks5')}://{proxy_config.get('host','127.0.0.1')}:{proxy_config.get('port',7890)}")
        self.proxy_info = proxy_config  # 保存用于 WebUI 展示

        # 创建 Telethon 客户端
        self.client = TelegramClient(
            session_file,
            self.api_id,
            self.api_hash,
            receive_updates=True,
            proxy=proxy
        )

        # 通知目标（支持多人）
        # 兼容旧格式 notify_target（单个）和新格式 notify_targets（列表）
        if 'notify_targets' in config:
            targets = config['notify_targets']
            self.notify_targets = targets if isinstance(targets, list) else [targets]
        elif 'notify_target' in config:
            self.notify_targets = [config['notify_target']]
        else:
            self.notify_targets = []

        # 监控群组
        self.monitor_groups = {
            group['group_id']: group
            for group in config['monitor_groups']
            if group.get('enabled', True)
        }

        # 关键词匹配器
        self.keyword_matcher = KeywordMatcher(config['keywords'])

        # 通知配置
        self.notification_config = config.get('notification', {})

        # 系统配置
        self.system_config = config.get('system', {})
        self.auto_reconnect = self.system_config.get('auto_reconnect', True)
        self.reconnect_delay = self.system_config.get('reconnect_delay', 30)
        self.retry_count = self.system_config.get('retry_count', 3)
        self.retry_delay = self.system_config.get('retry_delay', 5)

        # 统计数据库（共享）
        self.enable_statistics = enable_statistics
        if stats_db:
            self.stats_db = stats_db
        elif self.enable_statistics:
            self.stats_db = StatisticsDB()
        else:
            self.stats_db = None

        if self.enable_statistics:
            self.logger.info(f"[{self.account_name}] 统计功能已启用")

        # 红包处理器
        red_packet_config = config.get('red_packet', {})
        self.red_packet_handler = RedPacketHandler(
            config=red_packet_config,
            client=self.client,
            notify_entity=None,
            stats_db=self.stats_db,
            account_name=self.account_name
        )

        # 运行状态
        self.is_running = False
        self.notify_entities = []  # 多个通知目标实体
        self.username = None

        # 注册到全局注册表
        monitor_registry[self.account_name] = {
            'phone': self.phone,
            'online': False,
            'username': None,
            'groups_count': len(self.monitor_groups),
            'started_at': None,
            'proxy': f"{proxy_config.get('type','socks5')}://{proxy_config.get('host','127.0.0.1')}:{proxy_config.get('port',7890)}" if proxy_config and proxy_config.get('enabled', True) else None,
        }

        # 配置热重载器
        self.config_reloader = ConfigReloader(config_file, check_interval=5)
        self.config_reloader.register_callback(self._on_config_reload)
        self.logger.info(f"[{self.account_name}] 配置热重载已启用")

    async def start(self):
        """启动监控"""
        tag = f"[{self.account_name}]"
        try:
            # 连接并登录
            await self._connect_and_login()

            # 获取通知目标实体
            await self._get_notify_entity()

            # 注册事件处理器
            self._register_handlers()

            # 标记为运行中
            self.is_running = True

            # 更新注册表状态
            monitor_registry[self.account_name]['online'] = True
            monitor_registry[self.account_name]['started_at'] = datetime.now().isoformat()

            self.logger.info(f"{tag} 监控系统已启动，等待消息...")

            # 启动配置检查任务
            asyncio.create_task(self._config_check_loop())

            # 启动心跳保活任务
            asyncio.create_task(self._keep_alive_loop())

            # 保持运行
            await self.client.run_until_disconnected()

        except Exception as e:
            self.logger.error(f"{tag} 监控启动失败: {e}", exc_info=True)
            raise
        finally:
            await self.stop()

    async def stop(self):
        """停止监控"""
        self.is_running = False
        if self.account_name in monitor_registry:
            monitor_registry[self.account_name]['online'] = False
        if self.client.is_connected():
            await self.client.disconnect()
        self.logger.info(f"[{self.account_name}] 监控系统已停止")

    async def _connect_and_login(self):
        """连接并登录"""
        tag = f"[{self.account_name}]"
        self.logger.info(f"{tag} 正在连接 Telegram...")

        await self.client.connect()

        if not await self.client.is_user_authorized():
            self.logger.info(f"{tag} 账号未登录，开始登录流程...")

            # Telegram 只支持手机号登录
            if not self.phone.startswith('+'):
                self.logger.error(f"{tag} 错误：Telegram 只支持手机号登录，不支持邮箱登录")
                raise ValueError(f"{tag} phone 必须是手机号格式（以 + 开头），例如：+8613397161336")

            self.logger.info(f"{tag} 使用手机号登录: {self.phone}")

            # 发送验证码
            await self.client.send_code_request(self.phone)

            # 等待用户输入验证码
            code = input(f"{tag} 请输入验证码（发送到 Telegram App）: ")
            try:
                await self.client.sign_in(self.phone, code)
            except SessionPasswordNeededError:
                # 需要两步验证密码
                password = input(f"{tag} 请输入两步验证密码: ")
                await self.client.sign_in(password=password)

            self.logger.info(f"{tag} 登录成功！")
        else:
            self.logger.info(f"{tag} 账号已登录")

        # 获取当前用户信息
        me = await self.client.get_me()
        self.username = me.username
        monitor_registry[self.account_name]['username'] = me.username
        self.logger.info(f"{tag} 当前账号: {me.first_name} (@{me.username})")

        # 将 username 持久化写回 config.yaml
        self._save_username_to_config(me.username)

    def _save_username_to_config(self, username: str):
        """将登录后获取的 username 写回 config.yaml，以便 WebUI 离线时也能显示"""
        try:
            import yaml
            with open(self.config_file, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)

            updated = False
            for acc in cfg.get('monitor_accounts', []):
                if acc.get('phone') == self.phone or acc.get('name') == self.account_name:
                    if acc.get('username') != username:
                        acc['username'] = username
                        updated = True
                    break

            if updated:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
                self.logger.info(f"[{self.account_name}] 已保存 username @{username} 到配置文件")
        except Exception as e:
            self.logger.warning(f"[{self.account_name}] 保存 username 到配置失败: {e}")

    async def _get_notify_entity(self):
        """获取所有通知目标实体"""
        tag = f"[{self.account_name}]"
        self.logger.info(f"{tag} 正在获取通知目标（共 {len(self.notify_targets)} 个）...")

        self.notify_entities = []
        for i, target in enumerate(self.notify_targets):
            try:
                if 'username' in target:
                    username = target['username']
                    entity = await self.client.get_entity(username)
                    self.notify_entities.append(entity)
                    self.logger.info(f"{tag} 通知目标 {i+1}: {username}")
                elif 'user_id' in target:
                    user_id = target['user_id']
                    entity = await self.client.get_entity(user_id)
                    self.notify_entities.append(entity)
                    self.logger.info(f"{tag} 通知目标 {i+1} ID: {user_id}")
                else:
                    self.logger.warning(f"{tag} 通知目标 {i+1} 配置无效，跳过")
            except Exception as e:
                self.logger.error(f"{tag} 获取通知目标 {i+1} 失败: {e}")

        if not self.notify_entities:
            raise ValueError("没有可用的通知目标")

        self.logger.info(f"{tag} 成功解析 {len(self.notify_entities)} 个通知目标")
        # 设置红包处理器的通知实体
        self.red_packet_handler.notify_entities = self.notify_entities

    def _register_handlers(self):
        """注册消息事件处理器"""
        tag = f"[{self.account_name}]"
        self.logger.info(f"{tag} 注册消息处理器...")

        # 监听指定群组的新消息
        @self.client.on(events.NewMessage(chats=list(self.monitor_groups.keys())))
        async def handle_new_message(event):
            await self._handle_message(event)

        # 监听消息编辑（红包领取结果通常通过编辑消息展示）
        @self.client.on(events.MessageEdited(chats=list(self.monitor_groups.keys())))
        async def handle_edited_message(event):
            await self._handle_edited_message(event)

        self.logger.info(f"{tag} 已注册 {len(self.monitor_groups)} 个群组的消息监听")

    async def _config_check_loop(self):
        """配置检查循环"""
        while self.is_running:
            try:
                await asyncio.sleep(self.config_reloader.check_interval)
                self.config_reloader.check_and_reload()
            except Exception as e:
                self.logger.error(f"配置检查失败: {e}", exc_info=True)

    async def _keep_alive_loop(self):
        """心跳保活循环 - 保持客户端在线状态"""
        keep_alive_interval = self.system_config.get('keep_alive_interval', 15)
        while self.is_running:
            try:
                await asyncio.sleep(keep_alive_interval)
                # 发送心跳请求，保持连接活跃
                if self.client.is_connected():
                    await self.client.get_me()
                    self.logger.debug("心跳保活: 连接正常")
            except Exception as e:
                self.logger.warning(f"心跳保活失败: {e}")

    def _on_config_reload(self, new_config: Dict[str, Any]):
        """
        配置重载回调

        Args:
            new_config: 新配置
        """
        try:
            tag = f"[{self.account_name}]"
            self.logger.info(f"{tag} 开始应用新配置...")

            # 更新监控群组
            old_groups = set(self.monitor_groups.keys())
            new_groups_dict = {
                group['group_id']: group
                for group in new_config['monitor_groups']
                if group.get('enabled', True)
            }
            new_groups = set(new_groups_dict.keys())

            # 总是更新群组配置（mode 等字段可能变化）
            self.monitor_groups = new_groups_dict
            if self.account_name in monitor_registry:
                monitor_registry[self.account_name]['groups_count'] = len(self.monitor_groups)
            self.logger.info(f"{tag} 监控群组已更新: {len(self.monitor_groups)} 个群组")

            if old_groups != new_groups:
                # 群组列表变化，重新注册事件处理器
                self.client.remove_event_handler(self._handle_message)
                self._register_handlers()
                self.logger.info(f"{tag} 事件处理器已重新注册")

            # 更新关键词匹配器
            if new_config.get('keywords') != self.config.get('keywords'):
                self.keyword_matcher = KeywordMatcher(new_config['keywords'])
                self.logger.info(f"{tag} 关键词配置已更新")

            # 更新通知配置
            if new_config.get('notification') != self.notification_config:
                self.notification_config = new_config.get('notification', {})
                self.logger.info(f"{tag} 通知模板已更新")

            # 更新红包配置
            new_rp_config = new_config.get('red_packet', {})
            if new_rp_config != self.config.get('red_packet', {}):
                self.red_packet_handler.update_config(new_rp_config)
                self.logger.info(f"{tag} 红包配置已更新")

            # 更新配置引用
            self.config = new_config

            self.logger.info(f"{tag} 配置重载完成")

        except Exception as e:
            self.logger.error(f"{tag} 应用新配置失败: {e}", exc_info=True)

    async def _handle_message(self, event):
        """
        处理新消息

        Args:
            event: 消息事件
        """
        try:
            message = event.message
            text = message.text or ""
            chat = await event.get_chat()

            # 获取群组信息
            group_name = chat.title if hasattr(chat, 'title') else str(chat.id)
            group_id = chat.id

            # 获取发送者信息
            try:
                sender = await event.get_sender()
                sender_id = sender.id if sender else None
                sender_name = getattr(sender, 'first_name', None) or getattr(sender, 'username', None) or 'Unknown'
            except Exception:
                # 某些情况下无法获取发送者（匿名管理员、已删除账号等）
                sender_id = None
                sender_name = 'Unknown'

            # 跳过空消息
            if not text:
                self.logger.debug(f"[{group_name}] 收到非文本消息，跳过")
                return

            # DEBUG: 打印每条消息
            self.logger.debug(f"[{group_name}] {sender_name}: {text}")

            # 获取群组运行模式: monitor / red_packet / both
            group_config = self.monitor_groups.get(group_id, {})
            group_mode = group_config.get('mode', 'both')

            # === 红包自动领取检测 ===
            if group_mode in ('red_packet', 'both'):
                try:
                    handled = await self.red_packet_handler.handle_red_packet(
                        event, group_name=group_name, group_id=group_id
                    )
                    if handled:
                        # 红包已处理，记录统计后跳过普通关键词通知
                        if self.enable_statistics:
                            self.stats_db.record_message(
                                group_id=group_id,
                                group_name=group_name,
                                message_text=text,
                                sender_id=sender_id,
                                sender_name=sender_name,
                                matched_keyword="[红包自动领取]"
                            )
                        return
                except Exception as e:
                    self.logger.error(f"红包处理异常: {e}", exc_info=True)

            # === 关键词匹配 ===
            matched_keyword = None
            if group_mode in ('monitor', 'both'):
                matched_keyword = self.keyword_matcher.match(text)

            # 记录到统计数据库
            if self.enable_statistics:
                self.stats_db.record_message(
                    group_id=group_id,
                    group_name=group_name,
                    message_text=text,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    matched_keyword=matched_keyword
                )

            if matched_keyword:
                self.logger.info(f"检测到关键词: {matched_keyword}")
                self.logger.info(f"消息内容: {text[:50]}...")

                # 发送通知
                await self._send_notification(event, matched_keyword)

        except Exception as e:
            self.logger.error(f"处理消息失败: {e}", exc_info=True)

    async def _handle_edited_message(self, event):
        """
        处理编辑后的消息（红包领取结果通常通过编辑原消息展示）

        Args:
            event: 消息编辑事件
        """
        try:
            chat = await event.get_chat()
            group_id = chat.id
            group_name = chat.title if hasattr(chat, 'title') else str(chat.id)
            group_config = self.monitor_groups.get(group_id, {})
            group_mode = group_config.get('mode', 'both')
            if group_mode in ('red_packet', 'both'):
                await self.red_packet_handler.handle_edited_message(
                    event, group_name=group_name, group_id=group_id
                )
        except Exception as e:
            self.logger.error(f"处理编辑消息失败: {e}", exc_info=True)

    async def _send_notification(self, event, matched_keyword: str):
        """
        发送通知消息

        Args:
            event: 消息事件
            matched_keyword: 匹配到的关键词
        """
        try:
            message = event.message
            chat = await event.get_chat()

            # 获取群组名称
            group_name = chat.title if hasattr(chat, 'title') else str(chat.id)

            # 提取消息中的时间（优先从消息内容中提取）
            message_time = self._extract_time_from_message(message.text)
            if not message_time:
                # 如果提取不到，使用消息发送时间（转换为北京时间 UTC+8）
                from datetime import timedelta
                beijing_time = message.date + timedelta(hours=8)
                message_time = beijing_time.strftime('%Y-%m-%d %H:%M:%S')

            # 生成消息链接
            message_link = await self._generate_message_link(event)

            # 格式化通知消息
            notification_text = self._format_notification(
                group_name=group_name,
                keyword=matched_keyword,
                message_text=message.text,
                time=message_time,
                link=message_link
            )

            # 发送消息给所有通知目标（带重试）
            for entity in self.notify_entities:
                for attempt in range(self.retry_count):
                    try:
                        await self.client.send_message(
                            entity,
                            notification_text
                        )
                        self.logger.info(f"通知已发送")
                        break
                    except Exception as e:
                        if attempt < self.retry_count - 1:
                            self.logger.warning(f"发送失败，{self.retry_delay}秒后重试... ({attempt + 1}/{self.retry_count})")
                            await asyncio.sleep(self.retry_delay)
                        else:
                            self.logger.error(f"发送通知失败: {e}")

                # 如果配置了转发原始消息
                if self.notification_config.get('forward_original', False):
                    try:
                        await self.client.forward_messages(
                            entity,
                            message
                        )
                        self.logger.info("原始消息已转发")
                    except Exception as e:
                        self.logger.error(f"转发原始消息失败: {e}")

        except Exception as e:
            self.logger.error(f"发送通知失败: {e}", exc_info=True)

    async def _generate_message_link(self, event) -> str:
        """
        生成消息链接

        Args:
            event: 消息事件

        Returns:
            消息链接
        """
        try:
            chat = await event.get_chat()
            message_id = event.message.id

            if hasattr(chat, 'username') and chat.username:
                # 公开群组
                return f"https://t.me/{chat.username}/{message_id}"
            else:
                # 私密群组
                chat_id = str(chat.id).replace('-100', '')
                return f"https://t.me/c/{chat_id}/{message_id}"
        except Exception as e:
            self.logger.warning(f"生成消息链接失败: {e}")
            return "无法生成链接"

    def _extract_time_from_message(self, text: str) -> Optional[str]:
        """
        从消息内容中提取时间

        Args:
            text: 消息文本

        Returns:
            提取到的时间字符串，格式如 "17:45"，如果提取不到返回 None
        """
        if not text:
            return None

        import re
        from datetime import datetime

        # 匹配 "北京时间XX:XX" 格式
        pattern = r'北京时间(\d{1,2}:\d{2})'
        match = re.search(pattern, text)

        if match:
            time_str = match.group(1)
            # 添加今天的日期
            today = datetime.now().strftime('%Y-%m-%d')
            return f"{today} {time_str}"

        return None

    def _format_notification(
        self,
        group_name: str,
        keyword: str,
        message_text: str,
        time: str,
        link: str
    ) -> str:
        """
        格式化通知消息

        Args:
            group_name: 群组名称
            keyword: 关键词
            message_text: 消息文本
            time: 时间
            link: 链接

        Returns:
            格式化后的通知消息
        """
        # 使用配置的格式，如果没有则使用默认格式
        format_template = self.notification_config.get('format', """
🔔 关键词提醒
📍 群组：{group_name}
🏷️ 关键词：{keyword}
⏰ 时间：{time}
📝 消息：{message}
🔗 链接：{link}
        """).strip()

        # 是否包含链接
        include_link = self.notification_config.get('include_link', True)
        if not include_link:
            link = ""

        # 格式化消息
        notification = format_template.format(
            group_name=group_name,
            keyword=keyword,
            message=message_text,
            time=time,
            link=link
        )

        return notification
