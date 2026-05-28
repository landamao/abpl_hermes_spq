import time
from .logger import logger


class Status:
    """适配器全局状态追踪，通过类变量在各模块间共享"""

    # ========== 启动时间 ==========
    启动时间: float = time.time()

    # ========== WebSocket 连接 ==========
    ws连接次数: int = 0
    ws断开次数: int = 0
    ws发送成功: int = 0
    ws发送失败: int = 0
    ws收到消息: int = 0

    # ========== NapCat 发送 ==========
    NapCat发送成功: int = 0
    NapCat发送失败: int = 0

    # ========== 反向HTTP ==========
    反向HTTP请求: int = 0
    反向HTTP失败: int = 0

    # ========== 指令执行 ==========
    指令执行次数: int = 0
    指令成功: int = 0
    指令失败: int = 0

    # ========== LLM工具调用 ==========
    LLM工具调用: int = 0

    # ========== 贴表情 ==========
    贴表情成功: int = 0
    贴表情失败: int = 0

    # ========== 脱敏 ==========
    脱敏替换次数: int = 0

    @classmethod
    def uptime(cls) -> str:
        """返回可读的运行时长"""
        秒 = int(time.time() - cls.启动时间)
        天, 秒 = divmod(秒, 86400)
        时, 秒 = divmod(秒, 3600)
        分, 秒 = divmod(秒, 60)
        parts = []
        if 天:
            parts.append(f"{天}天")
        if 时:
            parts.append(f"{时}时")
        if 分:
            parts.append(f"{分}分")
        parts.append(f"{秒}秒")
        return ''.join(parts)

    @classmethod
    def 总结(cls) -> str:
        """返回格式化的状态摘要"""
        return (
            f"运行时长: {cls.uptime()}\n"
            f"\nWebSocket:\n"
            f"    连接{cls.ws连接次数}次"
            f"  断开{cls.ws断开次数}次\n"
            f"    发送成功{cls.ws发送成功}次"
            f"  发送失败{cls.ws发送失败}次\n"
            f"    收到{cls.ws收到消息}次\n"
            f"\nNapCat发送:\n"
            f"    成功{cls.NapCat发送成功}次"
            f"  失败{cls.NapCat发送失败}次\n"
            f"\n反向HTTP:\n"
            f"    请求{cls.反向HTTP请求}次"
            f"  失败{cls.反向HTTP失败}次\n"
            f"\n指令执行:\n"
            f"    总{cls.指令执行次数}次\n"
            f"    成功{cls.指令成功}次"
            f"  失败{cls.指令失败}次\n"
            f"\nLLM工具调用:"
            f"  {cls.LLM工具调用}次\n"
            f"\n贴表情:\n"
            f"    成功{cls.贴表情成功}次"
            f"  失败{cls.贴表情失败}次\n"
            f"\n脱敏替换:"
            f"  {cls.脱敏替换次数}次"
        )
    @classmethod
    def 重置(cls) -> None:
        """重置所有计数器（保留启动时间）"""
        for attr in dir(cls):
            if attr.startswith('_') or attr in ('启动时间', 'uptime', '总结', '重置'):
                continue
            if isinstance(getattr(cls, attr), int):
                setattr(cls, attr, 0)
        logger.info("状态计数器已重置")
