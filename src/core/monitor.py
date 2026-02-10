"""
Telegram 监控核心模块
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from telethon import TelegramClient, events
from telethon.tl.types import User, Channel
from telethon.errors import SessionPasswordNeededError

from .keyword_matcher import KeywordMatcher
from .statistics import StatisticsDB
from ..utils.config_reloader import ConfigReloader


class TelegramMonitor:
    """Telegram 监控器"""

    def __init__(self, config: Dict[str, Any], config_file: str = "config.yaml", enable_statistics=True):
        """
        初始化监控器

        Args:
            config: 配置字典
            config_file: 配置文件路径
            enable_statistics: 是否启用统计功能
        """
        self.config = config
        self.config_file = config_file
        self.logger = logging.getLogger("TelegramMonitor")

        # 账号B配置（监控账号）
        monitor_account = config['monitor_account']
        self.phone = monitor_account['phone']
        self.api_id = monitor_account['api_id']
        self.api_hash = monitor_account['api_hash']
        session_file = monitor_account.get('session_file', 'sessions/monitor.session')

        # 创建 session 目录
        Path(session_file).parent.mkdir(parents=True, exist_ok=True)

        # 创建 Telethon 客户端
        # receive_updates=True 确保客户端接收实时更新
        self.client = TelegramClient(
            session_file,
            self.api_id,
            self.api_hash,
            receive_updates=True
        )

        # 账号A配置（通知接收账号）
        self.notify_target = config['notify_target']

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

        # 统计数据库
        self.enable_statistics = enable_statistics
        if self.enable_statistics:
            self.stats_db = StatisticsDB()
            self.logger.info("统计功能已启用")

        # 运行状态
        self.is_running = False
        self.notify_entity = None

        # 配置热重载器
        self.config_reloader = ConfigReloader(config_file, check_interval=5)
        self.config_reloader.register_callback(self._on_config_reload)
        self.logger.info("配置热重载已启用")

    async def start(self):
        """启动监控"""
        try:
            # 连接并登录
            await self._connect_and_login()

            # 获取通知目标实体
            await self._get_notify_entity()

            # 注册事件处理器
            self._register_handlers()

            # 标记为运行中
            self.is_running = True

            self.logger.info("监控系统已启动，等待消息...")

            # 启动配置检查任务
            asyncio.create_task(self._config_check_loop())

            # 启动心跳保活任务
            asyncio.create_task(self._keep_alive_loop())

            # 保持运行
            await self.client.run_until_disconnected()

        except Exception as e:
            self.logger.error(f"监控启动失败: {e}", exc_info=True)
            raise
        finally:
            await self.stop()

    async def stop(self):
        """停止监控"""
        self.is_running = False
        if self.client.is_connected():
            await self.client.disconnect()
        self.logger.info("监控系统已停止")

    async def _connect_and_login(self):
        """连接并登录账号B"""
        self.logger.info(f"正在连接 Telegram...")

        await self.client.connect()

        if not await self.client.is_user_authorized():
            self.logger.info(f"账号未登录，开始登录流程...")

            # Telegram 只支持手机号登录
            if not self.phone.startswith('+'):
                self.logger.error(f"错误：Telegram 只支持手机号登录，不支持邮箱登录")
                self.logger.error(f"请在 config.yaml 中将 phone 改为手机号格式：+8613397161336")
                raise ValueError("phone 必须是手机号格式（以 + 开头），例如：+8613397161336")

            self.logger.info(f"使用手机号登录: {self.phone}")

            # 发送验证码
            await self.client.send_code_request(self.phone)

            # 等待用户输入验证码
            code = input("请输入验证码（发送到 Telegram App）: ")
            try:
                await self.client.sign_in(self.phone, code)
            except SessionPasswordNeededError:
                # 需要两步验证密码
                password = input("请输入两步验证密码: ")
                await self.client.sign_in(password=password)

            self.logger.info("登录成功！")
        else:
            self.logger.info("账号已登录")

        # 获取当前用户信息
        me = await self.client.get_me()
        self.logger.info(f"当前账号: {me.first_name} (@{me.username})")

    async def _get_notify_entity(self):
        """获取通知目标实体（账号A）"""
        self.logger.info("正在获取通知目标...")

        try:
            if 'username' in self.notify_target:
                username = self.notify_target['username']
                self.notify_entity = await self.client.get_entity(username)
                self.logger.info(f"通知目标: {username}")
            elif 'user_id' in self.notify_target:
                user_id = self.notify_target['user_id']
                self.notify_entity = await self.client.get_entity(user_id)
                self.logger.info(f"通知目标 ID: {user_id}")
            else:
                raise ValueError("notify_target 必须配置 username 或 user_id")

        except Exception as e:
            self.logger.error(f"获取通知目标失败: {e}")
            raise

    def _register_handlers(self):
        """注册消息事件处理器"""
        self.logger.info("注册消息处理器...")

        # 监听指定群组的新消息
        @self.client.on(events.NewMessage(chats=list(self.monitor_groups.keys())))
        async def handle_new_message(event):
            await self._handle_message(event)

        self.logger.info(f"已注册 {len(self.monitor_groups)} 个群组的消息监听")

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
            self.logger.info("开始应用新配置...")

            # 更新监控群组
            old_groups = set(self.monitor_groups.keys())
            new_groups_dict = {
                group['group_id']: group
                for group in new_config['monitor_groups']
                if group.get('enabled', True)
            }
            new_groups = set(new_groups_dict.keys())

            if old_groups != new_groups:
                self.monitor_groups = new_groups_dict
                self.logger.info(f"监控群组已更新: {len(self.monitor_groups)} 个群组")

                # 重新注册事件处理器
                self.client.remove_event_handler(self._handle_message)
                self._register_handlers()
                self.logger.info("事件处理器已重新注册")

            # 更新关键词匹配器
            if new_config.get('keywords') != self.config.get('keywords'):
                self.keyword_matcher = KeywordMatcher(new_config['keywords'])
                self.logger.info("关键词配置已更新")

            # 更新通知配置
            if new_config.get('notification') != self.notification_config:
                self.notification_config = new_config.get('notification', {})
                self.logger.info("通知模板已更新")

            # 更新配置引用
            self.config = new_config

            self.logger.info("配置重载完成")

        except Exception as e:
            self.logger.error(f"应用新配置失败: {e}", exc_info=True)

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

            # 匹配关键词
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

            # 发送消息（带重试）
            for attempt in range(self.retry_count):
                try:
                    await self.client.send_message(
                        self.notify_entity,
                        notification_text
                    )
                    self.logger.info(f"通知已发送到账号A")
                    break
                except Exception as e:
                    if attempt < self.retry_count - 1:
                        self.logger.warning(f"发送失败，{self.retry_delay}秒后重试... ({attempt + 1}/{self.retry_count})")
                        await asyncio.sleep(self.retry_delay)
                    else:
                        raise

            # 如果配置了转发原始消息
            if self.notification_config.get('forward_original', False):
                await self.client.forward_messages(
                    self.notify_entity,
                    message
                )
                self.logger.info("原始消息已转发")

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
