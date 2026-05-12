"""
消息处理模块

负责判断消息是否需要转发、构造 OneBot v11 格式事件体。
"""
import time
from astrbot.api.all import logger, Plain, At, Reply, MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


def _是指令前缀(event: AiocqhttpMessageEvent) -> bool:
    """精确判断消息是否以 / 开头"""
    return next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith("/")


class 消息管理器:
    """消息过滤与 OneBot 事件体构造"""

    def __init__(self, config: dict, emoji_manager=None):
        def 清理列表(lst):
            return [i.strip() for i in lst if i.strip()]

        过滤配置: dict = config['过滤配置']
        冲突配置: dict = config['冲突配置']
        approve配置: dict = config['approve配置']

        # 消息过滤配置
        self.触发关键词 = 过滤配置['触发关键词']
        self.触发艾特机器人 = 过滤配置['触发艾特机器人']
        self.允许的群组 = 清理列表(过滤配置['允许的群组'])
        self.允许的用户 = 清理列表(过滤配置['允许的用户'])
        self.转发所有消息 = 过滤配置['转发所有消息']
        self.引用唤醒 = 过滤配置['引用唤醒']

        # 冲突处理
        self.同时唤醒处理方式 = 冲突配置['同时唤醒处理方式']

        # /approve 配置
        self.approve_启用 = approve配置['approve_启用']
        self.approve_允许用户 = 清理列表(approve配置['approve_允许用户'])
        self.approve_拒绝提示 = approve配置.get('approve_拒绝提示', '')

        # /deny 配置
        self.deny_启用 = approve配置['deny_启用']
        self.deny_允许用户 = 清理列表(approve配置['deny_允许用户'])

        self.已转发键 = "[Hermes适配器] 已转发"

        # emoji_manager 用于引用唤醒的 ID 检测（延迟设置）
        self._emoji_manager = emoji_manager

    def set_emoji_manager(self, emoji_manager):
        """设置 emoji_manager 引用（用于引用唤醒的消息 ID 检测）"""
        self._emoji_manager = emoji_manager

    # ========== 过滤入口 ==========

    def 是否转发(self, event: AiocqhttpMessageEvent) -> bool:
        """
        判断消息是否需要转发给 Hermes。
        同时处理 /approve、/deny 的权限检查和 stop_event。
        """
        if self._检查转发条件(event):
            return self._处理冲突(event)
        return False

    def get_reject_message(self, event: AiocqhttpMessageEvent) -> str | None:
        """获取拒绝提示消息（供主类发送）"""
        # 当前只有 approve 拒绝提示
        return self.approve_拒绝提示 if self.approve_拒绝提示 else None

    # ========== 转发条件链 ==========

    def _检查转发条件(self, event: AiocqhttpMessageEvent) -> bool:
        """按优先级检查所有转发条件"""
        用户id = event.get_sender_id()
        消息内容 = event.get_message_str()
        消息链 = event.get_messages()
        群号 = event.get_group_id()

        # 1. /approve 命令
        if self.approve_启用 and self._是命令(event, 消息内容, "/approve"):
            if not self._检查权限(用户id, self.approve_允许用户):
                logger.info(f"[Hermes适配器] /approve 被拒绝: 用户 {用户id} 无权限")
                event.stop_event()
                return False
            logger.debug(f"[Hermes适配器] 转发消息（原因：/approve 授权命令），用户：{用户id}")
            return True

        # 2. /deny 命令
        if self.deny_启用 and self._是命令(event, 消息内容, "/deny"):
            if not self._检查权限(用户id, self.deny_允许用户):
                logger.info(f"[Hermes适配器] /deny 被拒绝: 用户 {用户id} 无权限")
                event.stop_event()
                return False
            logger.debug(f"[Hermes适配器] 转发消息（原因：/deny 授权命令），用户：{用户id}")
            return True

        # 3. 引用 Hermes 消息唤醒
        if self.引用唤醒 and self._emoji_manager:
            if 消息链 and isinstance(消息链[0], Reply):
                ref_id = str(消息链[0].id)
                if self._emoji_manager.是hermes消息(ref_id):
                    logger.info(f"[Hermes适配器] 检测到引用 Hermes 消息: {ref_id}，直接唤醒")
                    return True

        # 4. 转发所有消息
        if self.转发所有消息:
            logger.debug(f"[Hermes适配器] 转发消息（原因：转发所有消息），内容：{消息内容[:30]}...")
            return True

        # 5. 群组白名单
        if 群号 and self.允许的群组 and 群号 not in self.允许的群组:
            logger.debug(f"[Hermes适配器] 忽略消息（原因：群号 {群号} 不在允许的群组列表中）")
            return False

        # 6. 用户白名单
        if self.允许的用户 and 用户id not in self.允许的用户:
            logger.debug(f"[Hermes适配器] 忽略消息（原因：用户 {用户id} 不在允许的用户列表中）")
            return False

        # 7. @机器人触发
        if self.触发艾特机器人:
            自己id = event.get_self_id()
            for 组件 in 消息链:
                if isinstance(组件, At) and str(组件.qq) == 自己id:
                    logger.debug(f"[Hermes适配器] 转发消息（原因：@ 机器人触发），内容：{消息内容[:30]}...")
                    return True

        # 8. 关键词触发
        for 关键词 in self.触发关键词:
            if 关键词.lower() in 消息内容.lower():
                logger.debug(f"[Hermes适配器] 转发消息（原因：命中关键词 '{关键词}'），内容：{消息内容[:30]}...")
                return True

        # 9. 不满足任何条件
        logger.debug(f"[Hermes适配器] 忽略消息（原因：不满足任何转发条件），内容：{消息内容[:30]}...")
        return False

    # ========== 冲突处理 ==========

    def _处理冲突(self, event: AiocqhttpMessageEvent) -> bool:
        """处理 LLM 和 Hermes 同时唤醒时的冲突"""
        if self.同时唤醒处理方式 == '只用Hermes':
            logger.info("[Hermes适配器] 终止事件，使用hermes")
            event.stop_event()
            return True
        elif self.同时唤醒处理方式 == '都处理':
            if event.is_at_or_wake_command:
                logger.info("[Hermes适配器] 已同时唤醒")
            return True
        elif self.同时唤醒处理方式 == '不使用Hermes':
            if event.is_at_or_wake_command:
                logger.info("[Hermes适配器] llm已唤醒，不使用hermes")
                return False
            logger.info("[Hermes适配器] llm未唤醒，使用hermes")
            event.stop_event()
            return True
        return False

    # ========== 辅助方法 ==========

    @staticmethod
    def _是命令(event: AiocqhttpMessageEvent, 消息内容: str, 命令: str) -> bool:
        """检测消息是否为指定命令"""
        if hasattr(event, "get_original_message_str"):
            if event.get_original_message_str().startswith(命令):
                return True
        return 消息内容.startswith(命令) or (消息内容.startswith(命令[1:]) and _是指令前缀(event))

    @staticmethod
    def _检查权限(user_id: str, allowed_users: list) -> bool:
        """检查用户是否有权限"""
        if not allowed_users:
            return True
        return user_id in allowed_users

    # ========== OneBot 事件体构造 ==========

    async def 构造onebot事件体(self, event: AiocqhttpMessageEvent) -> dict:
        """
        构造 OneBot v11 格式的消息事件体，多方法回退（支持群聊和私聊）。
        """
        is_forwarded = event.get_extra(self.已转发键, False)

        # 方案1：优先使用原生 _raw_payload
        raw_payload = event.message_obj.raw_message.get('_raw_payload')
        if raw_payload:
            logger.debug("[Hermes适配器] 成功获取到 _raw_payload")
            if is_forwarded:
                logger.warning(f"消息已转发过，将使用随机id：{event.get_message_str()[:50]}")
                copy_payload = raw_payload.copy()
                copy_payload['message_id'] = int(time.time() * 1000) % 2147483647
                return copy_payload
            return raw_payload
        else:
            logger.debug("[Hermes适配器] _raw_payload 读取失败，回退原始消息字典")

        # 方案2：回退使用原始消息字典
        try:
            raw_message = dict(event.message_obj.raw_message)
            logger.debug("[Hermes适配器] 成功转换 raw_message")
            if is_forwarded:
                logger.warning(f"消息已转发过，将使用随机id：{event.get_message_str()[:50]}")
                raw_message['message_id'] = int(time.time() * 1000) % 2147483647
            return raw_message
        except Exception as e:
            logger.debug(f"[Hermes适配器] 原始消息转换失败，回退手动构造：{e}")

        # 方案3：最终兜底 - 手动构造完整事件
        return self._手动构造事件体(event, is_forwarded)

    def _手动构造事件体(self, event: AiocqhttpMessageEvent, is_forwarded: bool) -> dict:
        """手动构造 OneBot v11 事件体（兜底方案）"""
        群号 = event.get_group_id()
        用户id = event.get_sender_id()
        用户名 = event.get_sender_name()
        机器人id = event.get_self_id()
        原始消息链 = event.get_messages()

        # 过滤不兼容的嵌套 Reply 组件
        新消息链 = [c for c in 原始消息链 if not isinstance(c, Reply)]
        消息数组 = event._parse_onebot_json(MessageChain(chain=新消息链))

        # 重新插入干净的 Reply
        if 原始消息链 and isinstance(原始消息链[0], Reply):
            消息数组.insert(0, {"type": "reply", "data": {"id": str(原始消息链[0].id)}})

        # 消息 ID
        if is_forwarded:
            消息id = int(time.time() * 1000) % 2147483647
            logger.warning(f"消息已转发过，将使用随机id：{event.get_message_str()[:50]}")
        else:
            try:
                消息id = int(event.message_obj.message_id)
            except Exception as e:
                消息id = int(time.time() * 1000) % 2147483647
                logger.error(f"获取消息id失败，将使用随机id：{e}", exc_info=True)

        # 基础事件体
        事件体 = {
            "time": int(time.time()),
            "self_id": int(机器人id),
            "post_type": "message",
            "message_id": 消息id,
            "user_id": int(用户id),
            "message": 消息数组,
            "message_format": "array",
            "raw_message": event.message_obj.raw_message.get("raw_message", event.get_message_str()),
            "font": 0,
            "sender": {
                "user_id": int(用户id),
                "nickname": 用户名,
                "card": 用户名,
            }
        }

        # 群聊 / 私聊 区分
        if 群号:
            事件体["message_type"] = "group"
            事件体["sub_type"] = "normal"
            事件体["group_id"] = int(群号)
            try:
                事件体["sender"]["role"] = event.message_obj.raw_message['sender']['role']
                事件体["group_name"] = event.message_obj.raw_message['group_name']
            except Exception as e:
                logger.warning(f"获取用户 {用户名} 群身份失败：{e}")
        else:
            事件体["message_type"] = "private"
            事件体["sub_type"] = "临时会话" if 用户名 == "临时会话" else "friend"

        return 事件体
