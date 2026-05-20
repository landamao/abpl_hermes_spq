from .logger import logger

class MessageId:
    _缓存: dict = {}          # 改用 dict 保持插入顺序
    记录消息ID = True
    最大数量: int = 10000

    @classmethod
    def add(cls, mid: int | str | dict) -> None:
        原mid = mid
        if not cls.记录消息ID:
            return
        if isinstance(mid, dict):
            if 'message_id' in mid:
                mid = mid['message_id']
            elif 'data' in mid:
                mid = mid['data'].get('message_id')
        elif isinstance(mid, (int, str)):
            mid = str(mid)
        if not mid:
            logger.warning(f"[Hermes适配器] 记录消息ID未找到有效消息ID：{原mid}")
            return
        # 使用 dict 存储，key 为消息ID，value 可任意（此处用 None）
        cls._缓存[str(mid)] = None

        # 超出最大数量时删除一半最旧的条目
        if len(cls._缓存) > cls.最大数量:
            # 要删除的数量：最大数量的一半（与原逻辑一致）
            删除数 = cls.最大数量 // 2
            old_keys = list(cls._缓存.keys())[:删除数]
            for key in old_keys:
                del cls._缓存[key]

    @classmethod
    def has(cls, mid: int | str) -> bool:
        return str(mid) in cls._缓存

    @classmethod
    def clear(cls) -> None:
        cls._缓存.clear()