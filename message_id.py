from . import logger
class MessageId:
    message_id_set:set = set()
    记录消息ID = True
    最大数量: int = 100000
    @classmethod
    def add(cls, mid:int|str|dict) -> None:
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
        cls.message_id_set.add(str(mid))
        if len(cls.message_id_set) > cls.最大数量:
            for _ in range(cls.最大数量//2):
                cls.message_id_set.pop()  # 随机删除一个元素

    @classmethod
    def has(cls, mid:int|str) -> bool:
        return str(mid) in cls.message_id_set

    @classmethod
    def clear(cls) -> None:
        cls.message_id_set.clear()