import aiohttp, functools
from aiocqhttp import ActionFailed
from typing import Any, Callable
from astrbot.api.all import AstrBotConfig, BaseMessageComponent, MessageChain, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from .message_id import MessageId
from .status import Status
from .logger import logger


class 发送事件:
    """消息发送事件对象"""

    def __init__(self, data: dict):
        self._原始数据 = data
        self._额外信息 = {}
        self._已停止 = False
        self._停止原因 = ""
        self._发送结果: dict|None = None
        self._已发送 = False

    # ===== 数据访问 =====

    @property
    def data(self) -> dict:
        """获取完整 data（可直接修改）"""
        return self._原始数据

    @property
    def 动作(self) -> str:
        """获取动作类型，如 send_group_msg"""
        return self._原始数据.get('action', '')

    @property
    def 参数(self) -> dict:
        """获取参数"""
        return self._原始数据.get('params', {})

    @property
    def echo(self) -> Any:
        """获取 echo"""
        return self._原始数据.get('echo')

    @property
    def 消息(self):
        """快捷获取 message"""
        return self.参数.get('message')

    @property
    def 群号(self) -> str|None:
        """快捷获取 group_id"""
        return self.参数.get('group_id')

    @property
    def QQ号(self) -> str|None:
        """快捷获取 user_id"""
        return self.参数.get('user_id')

    @property
    def 是否群聊(self) -> bool:
        return self.动作 in ('send_group_msg', 'send_msg')

    @property
    def 是否私聊(self) -> bool:
        return self.动作 == 'send_private_msg'

    # ===== 发送结果（发送后钩子可用） =====

    @property
    def 结果(self) -> dict|None:
        """获取发送结果（仅发送后钩子可用）"""
        return self._发送结果

    @property
    def 已发送(self) -> bool:
        """消息是否已发送"""
        return self._已发送

    def 设置结果(self, 结果: dict):
        """设置发送结果"""
        self._发送结果 = 结果
        self._已发送 = True

    # ===== 流程控制 =====

    def 停止(self, 原因: str = ""):
        """阻止消息发送"""
        self._已停止 = True
        self._停止原因 = 原因
        if 原因:
            logger.debug(f"钩子停止发送: {原因}")

    @property
    def 已停止(self) -> bool:
        return self._已停止

    @property
    def 停止原因(self) -> str:
        return self._停止原因

    # ===== 额外信息（钩子之间传递状态） =====

    def 设置额外信息(self, key: str, value):
        """设置额外信息（不污染 data）"""
        self._额外信息[key] = value

    def 获取额外信息(self, key: str, default=None):
        """获取额外信息"""
        return self._额外信息.get(key, default)

    # ===== 便捷修改 =====

    def 设置data(self, key: str, value):
        """在 data 顶层设置字段"""
        self._原始数据[key] = value

    def 覆盖data(self, 新data: dict):
        """用新 data 完全覆盖原来的 data"""
        self._原始数据.clear()
        self._原始数据.update(新data)

    def 设置消息(self, 消息):
        """修改 message"""
        self.参数['message'] = 消息

    def 设置群号(self, 群号: str | int):
        """修改 group_id"""
        self.参数['group_id'] = str(群号)

    def 设置QQ号(self, qq: str | int):
        """修改 user_id"""
        self.参数['user_id'] = str(qq)

    def __repr__(self):
        状态 = "已停止" if self._已停止 else ("已发送" if self._已发送 else "进行中")
        return f"<发送事件 动作={self.动作} 群号={self.群号} QQ={self.QQ号} [{状态}]>"


class __消息发送钩子:
    """消息发送钩子系统

    两种钩子：
    1. 发送前 — 发送前执行，可修改 data、阻止发送
    2. 发送后 — 发送后执行，可读取发送结果、做后续处理

    钩子签名：async def xxx(事件: 发送事件, context) -> None
    - 事件：发送事件对象，包含 data、参数、群号等
    - context：上下文对象（通常是 NapCatSend 实例）

    用法：
        钩子 = 消息钩子系统()
        钩子.设置context类型(NapCatSend)  # 可选，提供类型提示

        @钩子.发送前
        async def 我的钩子(事件: 发送事件, context):
            # 通过 context 访问 NapCatSend 实例
            await context.贴表情(事件.结果)

            # 修改数据
            事件.设置消息("新内容")

            # 阻止发送
            事件.停止("原因：xxx")

        @钩子.发送后
        async def 发送后处理(事件: 发送事件, context):
            print(事件.结果)  # 发送结果
            await context.贴表情(事件.结果)
    """

    def __init__(self):
        self._发送前钩子: list[tuple[int, Callable]] = []
        self._发送后钩子: list[tuple[int, Callable]] = []

    def 发送前(self, func=None, *, 优先级: int = 100):
        """装饰器：注册发送前钩子

        Args:
            func: 钩子函数，签名 async def(事件: 发送事件, context) -> None
            优先级: 执行优先级，数字越小越先执行（默认100）
        """
        return self._注册钩子(self._发送前钩子, func, 优先级, "发送前")

    def 发送后(self, func=None, *, 优先级: int = 100):
        """装饰器：注册发送后钩子

        Args:
            func: 钩子函数，签名 async def(事件: 发送事件, context) -> None
            优先级: 执行优先级，数字越小越先执行（默认100）
        """
        return self._注册钩子(self._发送后钩子, func, 优先级, "发送后")

    @staticmethod
    def _注册钩子(列表, func, 优先级, 类型):
        """内部方法：注册钩子到指定列表"""

        def 装饰器(f):
            @functools.wraps(f)
            async def 包装(*args, **kwargs):
                return await f(*args, **kwargs)

            包装._钩子优先级 = 优先级
            包装._钩子名称 = f.__name__

            列表.append((优先级, 包装))
            列表.sort(key=lambda x: x[0])

            logger.info(f"已注册{类型}钩子: {f.__name__} (优先级={优先级})")
            return 包装

        if func is not None:
            return 装饰器(func)
        return 装饰器

    async def 执行发送前(self, 事件: 发送事件, context=None):
        """执行所有发送前钩子
        Args:
            事件: 发送事件对象
            context: 上下文对象（通常是 NapCatSend 实例）
        """
        if not self._发送前钩子:
            return
        logger.debug(f"执行发送前钩子，共 {len(self._发送前钩子)} 个 | {事件}")
        for 优先级, 钩子 in self._发送前钩子:
            if 事件.已停止:
                logger.debug("钩子已停止，跳过剩余发送前钩子")
                break
            名称 = getattr(钩子, '_钩子名称', '未知')
            try:
                await 钩子(事件, context)
                logger.debug(f"发送前钩子 [{名称}] 执行完成")
            except Exception as e:
                logger.error(f"发送前钩子 [{名称}] 执行失败: {e}", exc_info=True)

    async def 执行发送后(self, 事件: 发送事件, context=None):
        """执行所有发送后钩子
        Args:
            事件: 发送事件对象（事件.结果 可获取发送结果）
            context: 上下文对象（通常是 NapCatSend 实例）
        """
        if not self._发送后钩子:
            return
        logger.debug(f"执行发送后钩子，共 {len(self._发送后钩子)} 个 | {事件}")
        for 优先级, 钩子 in self._发送后钩子:
            名称 = getattr(钩子, '_钩子名称', '未知')
            try:
                await 钩子(事件, context)
                logger.debug(f"发送后钩子 [{名称}] 执行完成")
            except Exception as e:
                logger.error(f"发送后钩子 [{名称}] 执行失败: {e}", exc_info=True)

    def 列出所有(self) -> dict[str, list[str]]:
        """列出所有已注册的钩子"""
        return {
            "发送前": [
                f"[{优先级}] {getattr(钩子, '_钩子名称', '未知')}"
                for 优先级, 钩子 in self._发送前钩子
            ],
            "发送后": [
                f"[{优先级}] {getattr(钩子, '_钩子名称', '未知')}"
                for 优先级, 钩子 in self._发送后钩子
            ],
        }


# 全局钩子实例
消息钩子 = __消息发送钩子()


class NapCatSend:
    """所有NapCat统一请求模块"""

    def __init__(self, config: AstrBotConfig):
        self.config = config
        self.event:AiocqhttpMessageEvent|None = None
        连接配置: dict = config['连接配置']
        self.消息发送方式: str = 连接配置['消息发送方式'].strip()
        if self.消息发送方式 == "NapCat Http 服务器":
            self.NapCat_api_url: str = 连接配置['NapCat_api_url'].strip().rstrip('/')
            self.NapCat_api_token: str = 连接配置['NapCat_api_token'].strip()
            # aiohttp.ClientSession 需要在异步上下文中创建
            self.http会话 = None
            self._http_headers = {}
            if self.NapCat_api_token:
                self._http_headers["Authorization"] = f"Bearer {self.NapCat_api_token}"
        else:
            self.NapCat_api_url: str = ""
            self.NapCat_api_token: str = ""
            self.http会话 = None
        # emoji/脱敏/艾特/授权配置已移至 处理器 类

    def set_event(self, event:AiocqhttpMessageEvent) -> None:
        """设置event"""
        self.event = event

    async def 贴表情(self, mid: str|int|dict, 表情ID: int) -> dict:
        """给消息贴表情回应"""
        原mid = mid
        if isinstance(mid, dict):
            if 'message_id' in mid:
                mid = mid['message_id']
            elif 'data' in mid:
                mid = mid['data'].get('message_id')
        elif isinstance(mid, (int, str)):
            mid = str(mid)
        if not mid:
            logger.warning(f"贴表情未找到有效消息ID：{原mid}")
            return {}
        动作 = "set_msg_emoji_like"
        参数 = {
            "message_id": str(mid),
            "emoji_id": 表情ID,
            "set": True
        }
        结果 = await self.发送动作参数到NapCat(动作, 参数)
        if 结果.get('status') == 'ok' or 结果.get('retcode') == 0:
            Status.贴表情成功 += 1
        else:
            Status.贴表情失败 += 1
        logger.debug(f"贴表情发送结果：{结果}")
        return 结果

    async def 戳一戳(self, qq: str | int) -> dict:
        if not qq:
            logger.warning(f"（戳一戳）qq号不是有效值{qq}")
            return {}
        return await self.发送动作参数到NapCat("send_poke", {"user_id": str(qq)})

    async def 发送框架消息链到NapCat(self, 消息链:list[BaseMessageComponent]|MessageChain, 类型:str, ID:str, echo=None) -> dict:
        """发送框架类型的消息链到NapCat
        Args:
            消息链(list[BaseMessageComponent]|MessageChain): 框架消息链
            类型(str): 私聊or群聊
            ID(str)：私聊qq号或群号
        Returns:
            发送结果"""
        # 过滤不兼容的嵌套 Reply 组件
        原消息链 = 消息链
        if isinstance(消息链, MessageChain):
            原消息链 = 消息链.chain
        新消息链 = [c for c in 原消息链 if not isinstance(c, Reply)]
        消息组 = await self.event._parse_onebot_json(MessageChain(chain=新消息链))
        # 重新插入干净的 Reply
        if 原消息链 and isinstance(原消息链[0], Reply):
            消息组.insert(0, {"type": "reply", "data": {"id": str(原消息链[0].id)}})

        参数 = {'message': 消息组}

        if 类型 == "私聊":
            参数['user_id'] = ID
            动作 = "send_private_msg"
        elif 类型 == "群聊":
            动作 = "send_group_msg"
            参数['group_id'] = ID
        else:
            return {"echo": echo, "status": "failed", "retcode": -1, "data": None}
        return await self.发送data消息到NapCat({"action": 动作, "params": 参数, "echo": echo})

    async def 发送动作参数到NapCat(self, 动作:str, 参数:dict, echo=None) -> dict:
        """发送动作参数到NapCat"""
        return await self.发送data消息到NapCat({"action": 动作, "params": 参数, "echo": echo})

    async def 发送data消息到NapCat(self, data:dict) -> dict:
        """所有发送消息到NapCat统一接口"""
        事件 = 发送事件(data)

        # 发送前钩子
        await 消息钩子.执行发送前(事件, context=self)
        if 事件.已停止:
            return {"status": "intercepted", "retcode": -1, "data": None, "msg": 事件.停止原因}
        
        # 实际发送
        if self.消息发送方式 == "框架已有的WebSocket":
            结果 = await self._通过框架发送消息到NapCat(事件.data)
        elif self.消息发送方式 == "NapCat Http 服务器":
            结果 = await self._通过HTTP发送消息到NapCat(事件.data)
        else:
            logger.critical(f"意外未知的消息发送方式：{self.消息发送方式}\n原数据：{str(事件.data)}")
            结果 = await self._通过框架发送消息到NapCat(事件.data)
        
        # 发送后钩子
        事件.设置结果(结果)
        await 消息钩子.执行发送后(事件, context=self)
        
        return 事件.结果
    

    async def _通过框架发送消息到NapCat(self, data:dict) -> dict:
        """<说明>"""
        action = data.get('action', '')
        params = data.get('params', {})
        echo = data.get('echo')
        logger.debug("通过框架方法发送到NapCat")
        if self.event is None:
            logger.warning(f"event 为 None，无法通过框架发送。请先在群/私聊发送任意消息激活。原数据：{data}")
            return {"echo": echo, "status": "failed", "retcode": -1, "data": None, "msg": "event 未初始化，请先发送任意消息激活"}
        try:
            结果 = await self.event.bot.call_action(action, **params)
            返回 = {"echo": echo, "status": "ok", "retcode": 0, "data": 结果 or {}}
            if action in ("set_msg_emoji_like", "send_poke"):
                return 返回
            MessageId.add(结果)
            Status.NapCat发送成功 += 1
        except ActionFailed as e:
            Status.NapCat发送失败 += 1
            logger.error(f"转发消息到NapCat失败\n原数据：{data}\n错误信息：{e}", exc_info=True)
            结果 = e.__dict__.get('result')
            结果['echo'] = echo
            返回 = 结果
        except Exception as e:
            Status.NapCat发送失败 += 1
            logger.error(f"转发消息到NapCat失败\n原数据：{data}\n错误信息：{e}", exc_info=True)
            返回 = {"echo": echo, "status": "failed", "retcode": -1, "data": None, "msg": str(e)}
        return 返回

    async def _通过HTTP发送消息到NapCat(self, data: dict) -> dict:
        """通过 HTTP 会话转发 Hermes 消息到 NapCat"""
        action = data.get('action', '')
        params = data.get('params', {})
        echo = data.get('echo')
        logger.debug("通过HTTP发送到NapCat")

        if self.http会话 is None or self.http会话.closed:
            self.http会话 = aiohttp.ClientSession(headers=self._http_headers)

        try:
            url = self.NapCat_api_url + '/' + action
            async with self.http会话.post(url, json=params) as resp:
                结果 = await resp.json()
            logger.debug(f"API 响应: {action} -> {结果}")
            结果['echo'] = echo
            if action in ("set_msg_emoji_like", "send_poke"):
                return 结果
            MessageId.add(结果)
            Status.NapCat发送成功 += 1
            return 结果

        except Exception as e:
            Status.NapCat发送失败 += 1
            logger.error(f"API 调用失败\n原数据：{data}\n错误信息：{e}", exc_info=True)
            return {"echo": echo, "status": "failed", "retcode": 100, "msg": str(e), "data": None}
