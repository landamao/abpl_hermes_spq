"""
表情回应管理模块

管理表情回应配置、消息 ID 追踪（用于引用唤醒）、表情回应执行。
"""
import random
import asyncio
from astrbot.api.all import logger


class EmojiManager:
    """表情回应管理器"""

    def __init__(self, config: dict):
        emoji_config = config['emoji配置']

        self.回复消息贴表情: bool = emoji_config['回复消息贴表情']
        self.转发时贴表情: bool = emoji_config['转发时贴表情']

        # 解析表情 ID 列表
        raw_text: str = emoji_config['贴表情列表']
        try:
            cleaned = (raw_text.replace('\n', '').replace('\r', '')
                       .replace(' ', '').replace('\t', '').replace('，', ','))
            parts = [x for x in cleaned.split(',') if x]
            self.贴表情列表: tuple = tuple(map(int, parts))
            config['emoji配置']['贴表情列表'] = '，'.join(map(str, self.贴表情列表))
            config.save_config()
        except Exception as e:
            self.贴表情列表 = (12, 66, 76, 108, 122, 124, 144, 147, 175, 180, 192, 201, 282, 297)
            logger.error(
                f"[Hermes适配器] 解析 emoji ID 配置失败，已自动使用默认ID列表：{'，'.join(map(str, self.贴表情列表))}\n{e}",
                exc_info=True)

        # Hermes 消息 ID 追踪（用于引用唤醒）
        self._消息id集合: set = set()
        self._最大数量 = 100000

    def 记录消息id(self, message_id):
        """记录 Hermes 发送的消息 ID（用于引用唤醒检测）"""
        if not message_id:
            return
        self._消息id集合.add(str(message_id))
        if len(self._消息id集合) > self._最大数量:
            keep = self._最大数量 // 2
            self._消息id集合 = set(list(self._消息id集合)[-keep:])

    def 是hermes消息(self, message_id: str) -> bool:
        """检查消息 ID 是否为 Hermes 发送的"""
        return str(message_id) in self._消息id集合

    async def 贴表情(self, onebot_client, message_id: str | int):
        """给消息贴表情回应（异步，不阻塞）"""
        if not message_id:
            return
        try:
            emoji_id = random.choice(self.贴表情列表)
            asyncio.create_task(onebot_client.set_msg_emoji_like(message_id, emoji_id))
        except Exception as e:
            logger.error(f"[Hermes适配器] 表情回应发起失败: {e}")

    async def 发送并记录(self, onebot_client, send_coro, need_emoji: bool = True):
        """
        执行发送操作，记录消息 ID，并根据配置贴表情。

        Args:
            onebot_client: OneBotClient 实例
            send_coro: 发送协程（如 onebot_client.send_group_text(...)）
            need_emoji: 是否需要贴表情

        Returns:
            API 响应结果
        """
        result = await send_coro
        message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
        self.记录消息id(message_id)
        if need_emoji and self.回复消息贴表情:
            await self.贴表情(onebot_client, message_id)
        return result
