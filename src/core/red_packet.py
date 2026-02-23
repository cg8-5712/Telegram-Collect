"""
红包自动领取模块
监听群组红包消息，自动计算答案并点击按钮领取
"""
import re
import random
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List


class RedPacketHandler:
    """红包自动领取处理器"""

    # 默认正则模板（当配置中未指定时使用）
    DEFAULT_CALC_PATTERNS = [
        r'计算[：:]\s*(.+?)\s*[=＝]\s*[?？]',
        r'计算[：:]\s*(.+?)\s*[?？]',
        r'题目[：:]\s*(.+?)\s*[=＝]\s*[?？]',
        r'计算[：:]\s*(.+?)$',
    ]
    DEFAULT_AMOUNT_PATTERNS = [
        r'总金额[：:]\s*(\d+(?:\.\d+)?)\s*USDT',
        r'金额[：:]\s*(\d+(?:\.\d+)?)\s*USDT',
        r'总金额[：:]\s*(\d+(?:\.\d+)?)USDT',
    ]
    DEFAULT_COUNT_PATTERNS = [
        r'总数[：:]\s*(\d+)',
        r'个数[：:]\s*(\d+)',
        r'总数:\s*(\d+)',
    ]
    DEFAULT_RESULT_KEYWORDS = ['恭喜', '领取成功', '已领取', '获得']
    DEFAULT_RECEIVED_PATTERNS = [
        r'领取成功.*?获得\s*(\d+(?:\.\d+)?)\s*USDT',
        r'领取[了到]\s*(\d+(?:\.\d+)?)\s*USDT',
        r'获得[了到]?\s*(\d+(?:\.\d+)?)\s*USDT',
        r'恭喜.*?(\d+(?:\.\d+)?)\s*USDT',
    ]

    def __init__(self, config: Dict[str, Any], client, notify_entity=None, stats_db=None, account_name: str = ""):
        """
        初始化红包处理器

        Args:
            config: 红包配置
            client: Telethon 客户端
            notify_entity: 通知目标实体
            stats_db: 统计数据库实例
            account_name: 账号名称标识（多账号时区分来源）
        """
        self.logger = logging.getLogger("TelegramMonitor")
        self.client = client
        self.notify_entity = notify_entity
        self.stats_db = stats_db
        self.account_name = account_name

        # 加载配置
        self._load_config(config)

        # 防重复：记录最近处理过的消息 ID
        self._processed_messages = set()
        self._max_processed = 500

        self.logger.info(f"红包处理器已初始化 (enabled={self.enabled}, "
                         f"delay={self.delay_min}~{self.delay_max}s)")

    def _load_config(self, config: Dict[str, Any]):
        """从配置加载所有参数和正则模板"""
        self.enabled = config.get('enabled', False)
        self.delay_min = config.get('delay_min', 1.0)
        self.delay_max = config.get('delay_max', 3.5)
        self.notify = config.get('notify', True)

        # 关键词
        self.keywords = config.get('keywords', ['红包', '领取条件', '计算'])
        self.required_keywords = config.get('required_keywords', ['计算'])

        # 可配置的正则模板
        self.calc_patterns = config.get('calc_patterns', self.DEFAULT_CALC_PATTERNS)
        self.amount_patterns = config.get('amount_patterns', self.DEFAULT_AMOUNT_PATTERNS)
        self.count_patterns = config.get('count_patterns', self.DEFAULT_COUNT_PATTERNS)
        self.result_keywords = config.get('result_keywords', self.DEFAULT_RESULT_KEYWORDS)
        self.received_patterns = config.get('received_patterns', self.DEFAULT_RECEIVED_PATTERNS)

    def update_config(self, config: Dict[str, Any]):
        """热更新红包配置"""
        self._load_config(config)
        self.logger.info(f"红包配置已更新 (enabled={self.enabled})")

    def is_red_packet_message(self, text: str) -> bool:
        """判断是否为红包计算消息"""
        if not text or not self.enabled:
            return False

        has_required = any(kw in text for kw in self.required_keywords)
        if not has_required:
            return False

        has_keyword = any(kw in text for kw in self.keywords)
        if not has_keyword:
            return False

        expression, _ = self._extract_expression(text)
        return expression is not None

    def _extract_expression(self, text: str) -> Tuple[Optional[str], Optional[float]]:
        """从消息中提取计算式和答案"""
        for pattern in self.calc_patterns:
            try:
                match = re.search(pattern, text, re.MULTILINE)
            except re.error:
                continue
            if match:
                expression = match.group(1).strip()
                expression = expression.replace('=', '').replace('？', '').replace('?', '').strip()
                answer = self._safe_calculate(expression)
                if answer is not None:
                    return expression, answer

        return None, None

    def _safe_calculate(self, expression: str) -> Optional[float]:
        """安全计算数学表达式"""
        try:
            expr = expression.strip()
            expr = expr.replace('＋', '+').replace('－', '-').replace('×', '*').replace('÷', '/')
            expr = expr.replace('（', '(').replace('）', ')')

            if not re.match(r'^[\d\s\+\-\*/\(\)\.]+$', expr):
                self.logger.warning(f"表达式包含非法字符: {expr}")
                return None

            result = eval(expr)
            return result
        except Exception as e:
            self.logger.error(f"计算错误: {expression} -> {e}")
            return None

    def _parse_red_packet_info(self, text: str) -> Dict[str, Any]:
        """解析红包消息，提取完整信息"""
        data = {}

        for pattern in self.amount_patterns:
            try:
                match = re.search(pattern, text)
            except re.error:
                continue
            if match:
                data['total_amount'] = float(match.group(1))
                break

        for pattern in self.count_patterns:
            try:
                match = re.search(pattern, text)
            except re.error:
                continue
            if match:
                data['total_count'] = int(match.group(1))
                break

        expression, answer = self._extract_expression(text)
        if expression:
            data['expression'] = expression
            data['answer'] = answer

        return data

    def _find_answer_button(self, buttons, answer) -> Optional[Any]:
        """在按钮列表中查找正确答案按钮"""
        if answer is None or not buttons:
            return None

        if isinstance(answer, float) and answer.is_integer():
            answer_str = str(int(answer))
        else:
            answer_str = str(answer)

        self.logger.debug(f"查找答案按钮: {answer_str}")

        for row in buttons:
            for button in row:
                btn_text = button.text.strip()

                if not re.match(r'^[\d\.\-]+$', btn_text):
                    continue

                if btn_text == answer_str:
                    return button

                try:
                    btn_value = float(btn_text)
                    if abs(btn_value - float(answer_str)) < 0.001:
                        return button
                except ValueError:
                    continue

        return None

    async def handle_red_packet(self, event, group_name: str = "", group_id: int = 0) -> bool:
        """
        处理红包消息（主入口）

        Args:
            event: Telethon 消息事件
            group_name: 群组名称
            group_id: 群组 ID

        Returns:
            是否成功处理
        """
        if not self.enabled:
            return False

        message = event.message
        text = message.text or ""
        msg_id = message.id

        # 防重复处理
        if msg_id in self._processed_messages:
            return False
        self._processed_messages.add(msg_id)

        if len(self._processed_messages) > self._max_processed:
            sorted_ids = sorted(self._processed_messages)
            self._processed_messages = set(sorted_ids[len(sorted_ids) // 2:])

        if not self.is_red_packet_message(text):
            return False

        self.logger.info(f"{'=' * 50}")
        self.logger.info(f"[{group_name}] 检测到红包计算消息!")

        data = self._parse_red_packet_info(text)
        self.logger.info(f"  总金额: {data.get('total_amount', '?')} USDT")
        self.logger.info(f"  总数: {data.get('total_count', '?')}")
        self.logger.info(f"  计算式: {data.get('expression', '?')}")
        self.logger.info(f"  答案: {data.get('answer', '?')}")

        answer = data.get('answer')
        if answer is None:
            self.logger.warning("未能计算出答案，跳过")
            return False

        # 获取消息按钮
        try:
            buttons = await message.get_buttons()
        except Exception as e:
            self.logger.error(f"获取按钮失败: {e}")
            return False

        if not buttons:
            self.logger.warning("消息中没有找到按钮")
            return False

        btn_count = sum(len(row) for row in buttons)
        self.logger.info(f"  找到 {btn_count} 个按钮:")
        for i, row in enumerate(buttons):
            for j, btn in enumerate(row):
                self.logger.debug(f"    [{i},{j}] {btn.text}")

        answer_button = self._find_answer_button(buttons, answer)

        if not answer_button:
            self.logger.warning(f"未找到答案为 {answer} 的按钮")
            # 记录失败到数据库
            if self.stats_db:
                self.stats_db.record_red_packet(
                    group_id=group_id, group_name=group_name,
                    total_amount=data.get('total_amount'),
                    total_count=data.get('total_count'),
                    expression=data.get('expression'),
                    answer=answer,
                    success=False, error_message="未找到匹配按钮"
                )
            await self._send_notify(
                f"⚠️ 红包处理失败\n"
                f"📍 群组：{group_name}\n"
                f"📝 题目: {data.get('expression')} = ?\n"
                f"✅ 答案: {answer}\n"
                f"❌ 原因: 未找到匹配的按钮"
            )
            return False

        self.logger.info(f"  找到答案按钮: [{answer_button.text}]")

        # === 关键：随机延迟，防封 ===
        delay = random.uniform(self.delay_min, self.delay_max)
        self.logger.info(f"  等待 {delay:.2f} 秒后点击...")
        await asyncio.sleep(delay)

        # 点击按钮
        click_result = None
        try:
            click_result = await answer_button.click()
            self.logger.info(f"  已点击按钮 [{answer_button.text}]")
        except Exception as e:
            self.logger.error(f"  点击按钮失败: {e}")
            if self.stats_db:
                self.stats_db.record_red_packet(
                    group_id=group_id, group_name=group_name,
                    total_amount=data.get('total_amount'),
                    total_count=data.get('total_count'),
                    expression=data.get('expression'),
                    answer=answer,
                    clicked_button=answer_button.text,
                    delay_seconds=delay,
                    success=False, error_message=str(e)
                )
            await self._send_notify(
                f"❌ 红包按钮点击失败\n"
                f"📍 群组：{group_name}\n"
                f"📝 题目: {data.get('expression')} = {answer}\n"
                f"❌ 错误: {e}"
            )
            return False

        # 解析点击回调结果（callback query answer / bot alert）
        # 如 "领取成功！获得 0.2 USDT"
        amount_received = None
        callback_text = ""
        if click_result:
            # BotCallbackAnswer 对象有 .message 属性
            callback_text = getattr(click_result, 'message', '') or ''
            if callback_text:
                self.logger.info(f"  回调响应: {callback_text}")
                amount_received = self._extract_received_amount(callback_text)
                if amount_received is not None:
                    self.logger.info(f"  💰 领取金额: {amount_received} USDT")

        # 记录到数据库
        record_id = None
        if self.stats_db:
            record_id = self.stats_db.record_red_packet(
                group_id=group_id, group_name=group_name,
                total_amount=data.get('total_amount'),
                total_count=data.get('total_count'),
                expression=data.get('expression'),
                answer=answer,
                clicked_button=answer_button.text,
                delay_seconds=delay,
                success=True
            )
            # 如果已获取到领取金额，立即更新记录
            if amount_received is not None and record_id:
                self.stats_db.update_red_packet_result(record_id, amount_received)

        # 发送通知
        beijing_now = datetime.utcnow() + timedelta(hours=8)
        received_line = ""
        if amount_received is not None:
            received_line = f"🎉 领取金额: {amount_received} USDT\n"
        elif callback_text:
            received_line = f"📨 回调: {callback_text}\n"

        account_line = f"👤 账号：{self.account_name}\n" if self.account_name else ""
        await self._send_notify(
            f"🎁 红包自动领取报告\n"
            f"━━━━━━━━━━━━━━\n"
            f"{account_line}"
            f"📍 群组：{group_name}\n"
            f"💰 总金额: {data.get('total_amount', '?')} USDT\n"
            f"🔢 总数: {data.get('total_count', '?')} 个\n"
            f"📝 题目: {data.get('expression', '?')} = ?\n"
            f"✅ 答案: {answer}\n"
            f"🖱️ 点击: [{answer_button.text}]\n"
            f"⏱️ 延迟: {delay:.2f}s\n"
            f"{received_line}"
            f"⏰ 时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━"
        )

        self.logger.info(f"{'=' * 50}")
        return True

    async def _send_notify(self, text: str):
        """发送通知消息"""
        if not self.notify or not self.notify_entity:
            return
        try:
            await self.client.send_message(self.notify_entity, text)
            self.logger.debug("红包通知已发送")
        except Exception as e:
            self.logger.error(f"发送红包通知失败: {e}")

    async def handle_edited_message(self, event, group_name: str = "", group_id: int = 0):
        """处理编辑后的红包消息（领取结果通常通过编辑消息展示）"""
        if not self.enabled or not self.notify:
            return

        text = event.message.text or ""

        if not any(kw in text for kw in self.result_keywords):
            return

        amount = self._extract_received_amount(text)
        if amount:
            # 更新数据库中最近一条该群组的记录
            if self.stats_db:
                try:
                    history = self.stats_db.get_red_packet_history(
                        limit=1, group_id=group_id
                    )
                    if history['records']:
                        self.stats_db.update_red_packet_result(
                            history['records'][0]['id'], amount
                        )
                except Exception as e:
                    self.logger.error(f"更新红包领取金额失败: {e}")

            account_line = f"👤 账号：{self.account_name}\n" if self.account_name else ""
            await self._send_notify(
                f"💰 红包领取成功！\n"
                f"{account_line}"
                f"📍 群组：{group_name}\n"
                f"🎉 获得: {amount} USDT"
            )

    def _extract_received_amount(self, text: str) -> Optional[float]:
        """从消息中提取领取到的金额"""
        for pattern in self.received_patterns:
            try:
                match = re.search(pattern, text)
            except re.error:
                continue
            if match:
                return float(match.group(1))
        return None
