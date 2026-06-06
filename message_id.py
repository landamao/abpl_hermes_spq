from .logger import logger

class MessageId:
    _缓存: dict[str,None] = {}          # 改用 dict 保持插入顺序
    记录消息ID = True
    最大数量: int = 10000
    授权ID:dict[str,str|None] = {}

    @classmethod
    def add_sq(cls, mid: int | str | dict, ID:int|str) -> None:
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
            logger.warning(f"记录消息ID未找到有效消息ID：{原mid}")
            return

        cls.授权ID[str(ID)] = str(mid)

    @classmethod
    def cl_sq(cls, ID:int|str) -> None:
        cls.授权ID[str(ID)] = None

    @classmethod
    def eq_sq(cls, mid: int | str, ID:int|str) -> bool:
        return cls.授权ID.get(str(ID)) == str(mid)

    @classmethod
    def has_sq(cls, ID:int|str) -> bool:
        return bool(cls.授权ID.get(str(ID)))

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
            logger.warning(f"记录消息ID未找到有效消息ID：{原mid}")
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