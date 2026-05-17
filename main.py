import sys, json, asyncio, websockets
from astrbot.api.event import filter
from astrbot.api.provider import LLMResponse
from astrbot.api.all import Star, Context, AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from . import Tools
from .logger import *
from .napcat_send import NapCatSend

class Hermes适配器(Star):

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        debug("[Hermes适配器] __init__完成")
        super().__init__(context)
        self.config: AstrBotConfig = config
        self.event: list[AiocqhttpMessageEvent|None] = [None]  # 使用列表共享实时变化的event对象

        # ========== 连接配置 ==========
        连接配置: dict = config['连接配置']
        self.hermes_ws_url: str = 连接配置['hermes_ws_url'].strip().rstrip('/')
        self.hermes_token: str = 连接配置['hermes_token'].strip()
        self.消息发送方式: str = 连接配置['消息发送方式'].strip()
        if self.消息发送方式 == "NapCat Http 服务器":
            self.开启反向HTTP: bool = False
        else:
            self.开启反向HTTP: bool = 连接配置['开启反向HTTP']
        if self.开启反向HTTP:
            self.反向HTTP地址: str = 连接配置['反向HTTP地址'].strip()
            self.反向HTTP令牌: str = 连接配置['反向HTTP令牌'].strip()
        else:
            self.反向HTTP地址: str = ""
            self.反向HTTP令牌: str = ""

        try:
            管理员列表 = context.get_config()["admins_id"]
        except Exception as e:
            error("[Hermes适配器] 获取管理员列表失败，你可在代码中手动配置管理员，错误信息：\n" + str(e))
            管理员列表 = []

        def 清理列表(l: list) -> list[str]:
            """去除列表中每个元素的空白字符，并过滤掉空字符串"""
            return list(dict.fromkeys([i.strip() for i in l if i.strip()]))

        def 解析all(l: list[str], ad=True) -> list[str]:
            """解析all和admin"""
            if "all" in l:
                return ["all"]
            if ad and "admin" in l:
                l.extend(管理员列表)
            return list(dict.fromkeys(l))

        # ========== 过滤配置 ==========
        过滤配置: dict = config['过滤配置']
        self.允许的群组: list[str] = 解析all(清理列表(过滤配置['允许的群组']), False)
        self.允许的用户: list[str] = 解析all(清理列表(过滤配置['允许的用户']))
        self.私聊允许的用户: list[str] = 解析all(清理列表(过滤配置['私聊允许的用户']))
        self.私聊转发所有消息: bool = 过滤配置['私聊转发所有消息']
        self.引用唤醒: bool = 过滤配置['引用唤醒']
        self.艾特机器人触发: bool = 过滤配置['艾特机器人触发']
        self.触发关键词: list[str] = 清理列表(过滤配置['触发关键词'])
        self.同时唤醒处理方式: str = 过滤配置['同时唤醒处理方式']

        # ========== 授权配置 ==========
        授权配置: dict = config['授权配置']
        self.允许approve的用户: list[str] = 解析all(清理列表(授权配置['允许approve的用户']))
        self.允许deny的用户: list[str] = 解析all(清理列表(授权配置['允许deny的用户']))
        self.无权限处理方式: str = 授权配置['无权限处理方式']
        self.自定义拒绝信息: str = 授权配置['自定义拒绝信息']
        self.approve无权限提示: str = 授权配置['approve无权限提示']
        self.允许其他指令的用户: list[str] = 解析all(清理列表(授权配置['允许其他指令的用户']))
        self.开启中文映射: bool = 授权配置['开启中文映射']

        self.转发时贴表情: bool = config['emoji配置']['转发时贴表情']
        self.过滤llm结果: bool = config['脱敏配置']['过滤llm结果']
        self.替换目标: str = config['脱敏配置']['替换目标']
        自动添加token = config['脱敏配置']['自动添加token']

        if 自动添加token:
            config['脱敏配置']['敏感字符列表'].extend([
                连接配置['hermes_token'], 连接配置['NapCat_api_token'], 连接配置['反向HTTP令牌']
            ])
        self.敏感字符列表:list[str] = config['脱敏配置']['敏感字符列表']

        self.ws服务 = None
        self.ws任务 = None
        self.ws已连接 = False
        self.ws重连延迟 = 1.0
        Tools.记录消息ID = self.引用唤醒
        self.NapCatSend = NapCatSend(config, self.event)
        if self.开启反向HTTP:
            from .reverse_http import ReverseHTTPServer
            self.反向HTTP = ReverseHTTPServer(self.NapCatSend, config)

        if config['脱敏配置']['自动保存']:
            config.save_config()

        debug("[Hermes适配器] __init__完成")
    # ========== 消息处理 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    async def 接收消息(self, event: AiocqhttpMessageEvent):
        """监听所有消息（群聊+私聊），存储 event 并转发给 Hermes"""
        消息链 = event.get_messages()
        if not 消息链:
            return

        if not isinstance(event, AiocqhttpMessageEvent):
            return
        raw:dict = dict(event.message_obj.raw_message)
        event.get_group_id()
        self.event[0] = event

        转发, data = await self.检查转发到Hermes(event)
        if 转发 and self.处理冲突(event):
            来源 = "群聊" if raw.get('group_id') else "私聊"
            await self.发送ws消息(data)
            if self.转发时贴表情:
                await self.NapCatSend.贴表情(data)
            info(f"[Hermes适配器] 已转发[{Tools.用户名(raw)}] 的{来源}消息到 Hermes：{event.message_obj.raw_message.get('raw_message')}")
            return
        debug(f"[Hermes适配器] 转发检测未通过")

    @filter.on_llm_response(priority=sys.maxsize)
    async def llm请求后(self, _, resp: LLMResponse):
        """llm请求后过滤敏感字符"""
        llm文本 = resp.completion_text
        for 敏感词 in self.敏感字符列表:
            llm文本 = llm文本.replace(敏感词, self.替换目标)
        resp.completion_text = llm文本

    @filter.llm_tool("hermes_agent")
    async def hermes_agent(self, event: AiocqhttpMessageEvent, task: str = "") -> str:
        """
        调用 Hermes Agent 执行任务或命令。Hermes 是一个强大的 AI Agent，可以执行各种复杂任务。
        当用户需要执行复杂任务、查询信息、处理数据、调用其他插件功能时，可以使用此工具。

        Args:
            task(string): 任务描述，详细说明需要完成什么任务
        """
        task = task.strip()
        if not task:
            return "请输入task参数（任务描述）"
        if not isinstance(event, AiocqhttpMessageEvent):
            return "当前平台不支持Hermes"
        try:
            if self.ws已连接:
                return "Hermes Agent 未连接，请稍后再试"
            NapCat事件体 = Tools.构造文本NapCat事件体(event, task)
            await self.发送ws消息(NapCat事件体)
            return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"
        except Exception as e:
            error(f"[Hermes适配器] LLM工具执行失败: {e}", exc_info=True)
            return f"执行失败: {str(e)}"

    # ========== 转发Hermes判断 ==========

    def 处理冲突(self, event: AiocqhttpMessageEvent) -> bool:
        """处理 LLM 和 Hermes 同时唤醒时的冲突"""
        if self.同时唤醒处理方式 == '只用Hermes':
            info("[Hermes适配器] 终止事件，使用hermes")
            event.stop_event()
            return True
        elif self.同时唤醒处理方式 == '都处理':
            if event.is_at_or_wake_command:
                info("[Hermes适配器] 已同时唤醒")
            return True
        elif self.同时唤醒处理方式 == '不使用Hermes':
            if event.is_at_or_wake_command:
                info("[Hermes适配器] llm已唤醒，不使用hermes")
                return False
            info("[Hermes适配器] llm未唤醒，使用hermes")
            event.stop_event()
            return True
        return False

    async def 检查转发到Hermes(self, event: AiocqhttpMessageEvent) -> tuple[bool, dict]:
        """检查是否通过过滤配置"""
        raw: dict = dict(event.message_obj.raw_message)
        群号 = str(raw.get('group_id', ""))
        qq = str(raw.get('user_id', ""))
        if not 群号:
            if not Tools.all判断(self.私聊允许的用户, qq):
                return False, raw
            if  self.私聊转发所有消息:
                return True, raw
            return False, raw
        if not Tools.all判断(self.允许的群组, 群号):
            return False, raw
        if not Tools.all判断(self.允许的用户, qq):
            return False, raw
        if self.引用唤醒 and (message_id := Tools.引用ID(raw)) and Tools.mhas(message_id):
            return True, raw
        if self.艾特机器人触发 and event.get_self_id() in Tools.艾特ID(raw):
            return True, raw
        try:
            text = raw['message'][0]['data']['text']
        except (KeyError, IndexError):
            text = ""
        if text in Tools.授权命令映射:
            text = Tools.授权命令映射[text]
        if text.startswith("/approve"):
            if Tools.all判断(self.允许approve的用户, qq):
                return True, Tools.构造文本NapCat事件体(event, text)
            else:
                if self.approve无权限提示:
                    await self.发送文本给NapCat(event, self.approve无权限提示)
                if self.无权限处理方式 == "自动发送/deny拒绝命令":
                    return True, Tools.构造文本NapCat事件体(event, '/deny')
                elif self.无权限处理方式 == "发送自定义拒绝信息给Hermes":
                    return True, Tools.构造文本NapCat事件体(event, self.自定义拒绝信息)
                return False, raw
        elif text.startswith("/deny"):
            if Tools.all判断(self.允许deny的用户, qq):
                return True, Tools.构造文本NapCat事件体(event, text)
            return False, raw
        elif text.startswith("/"):
            if Tools.all判断(self.允许其他指令的用户, qq):
                return True, Tools.构造文本NapCat事件体(event, text)
            return False, raw
        if any(i in text for i in self.触发关键词):
            return True, raw
        return False, raw

    async def 发送文本给NapCat(self, event: AiocqhttpMessageEvent, 文本:str) -> dict:
        """通过当前event判断群聊或私聊直接发送文本"""
        raw: dict = dict(event.message_obj.raw_message)
        if raw.get('group_id'):
            动作 = "send_group_msg"
            参数 = {
                "message_type": "group",
                "group_id": raw.get('group_id'),
                "message": 文本
            }
        else:
            动作 = "send_private_msg"
            参数 = {
                "message_type": "private",
                "user_id": raw.get('user_id'),
                "message": 文本
            }
        结果 = await self.NapCatSend.发送动作参数到NapCat(动作, 参数)
        return 结果


    # ========== Hermes WebSocket ==========

    async def ws开始(self):
        """启动 WebSocket 连接循环"""
        self.ws任务 = asyncio.create_task(self.ws连接循环())

    async def ws停止(self):
        """停止 WebSocket 连接"""
        if self.ws任务:
            self.ws任务.cancel()
            try:
                await self.ws任务
            except asyncio.CancelledError:
                pass
        if self.ws服务:
            await self.ws服务.close()

    async def 发送ws消息(self, data: dict):
        """发送 WebSocket 消息"""
        if self.ws已连接:
            try:
                await self.ws服务.send(json.dumps(data, ensure_ascii=False))
                debug(f"[Hermes适配器] 已发送数据到Hermes：{data}")
            except Exception as e:
                error(f"[Hermes适配器] WebSocket 发送失败: {e}", exc_info=True)
                debug(f"[Hermes适配器] 发送失败，原始数据: {data}")
                self.ws已连接 = False

    async def ws连接循环(self):
        """WebSocket 重连循环"""
        while True:
            try:
                await self.连接到ws()
            except asyncio.CancelledError:
                break
            except Exception as e:
                error(f"[Hermes适配器] WebSocket 连接异常: {e}")

            if self.ws已连接:
                self.ws已连接 = False
                info("[Hermes适配器] WebSocket 断开，准备重连...")

            info(f"[Hermes适配器] 等待 {self.ws重连延迟:.1f}s 后重连...")
            await asyncio.sleep(self.ws重连延迟)

    async def 连接到ws(self):
        """连接到 Hermes WebSocket 并监听消息"""
        头 = {}
        if self.hermes_token:
            头['Authorization'] = f'Bearer {self.hermes_token}'

        info(f"[Hermes适配器] 正在连接到 Hermes: {self.hermes_ws_url}")

        async with websockets.connect(
            self.hermes_ws_url,
            additional_headers=头,
            ping_interval=20,
            ping_timeout=60
        ) as ws:
            self.ws服务 = ws
            self.ws已连接 = True
            self.ws重连延迟 = 1.0

            info("[Hermes适配器] WebSocket 已连接到 Hermes")

            await self.发送ws消息({
                "type": "connect",
                "platform": "qqonebot",
                "self_id": "astrbot",
                "data": {}
            })

            async for 原始消息 in ws:
                try:
                    await self.处理ws消息(原始消息)
                    info("[Hermes适配器] 收到来自Hermes的消息")
                except Exception as e:
                    error(f"[Hermes适配器] 处理 WebSocket 消息失败: {e}", exc_info=True)

    async def 处理ws消息(self, raw):
        """<说明>"""
        data = json.loads(raw)
        debug(f"[Hermes适配器] 转发来自Hermes的消息到NapCat的数据：{data}")
        结果 = await self.NapCatSend.发送data消息到NapCat(data)
        debug(f"[Hermes适配器] 转发来自Hermes的消息到NapCat的结果：{结果}")
        await self.发送ws消息(结果)

    # ========== 生命周期 ==========

    async def initialize(self):
        """异步初始化"""
        debug("[Hermes适配器] initialize开始")
        if self.开启反向HTTP:
            await self.反向HTTP.start()
        await self.ws开始()
        await asyncio.sleep(0.1)
        info("[Hermes适配器] 初始化完成")
        debug("[Hermes适配器] initialize完成")

    async def terminate(self):
        """插件终止时清理资源"""
        if self.开启反向HTTP:
            await self.反向HTTP.stop()
        await self.ws停止()
        if self.NapCatSend.http会话 and not self.NapCatSend.http会话.closed:
            await self.NapCatSend.http会话.close()
            info("[Hermes适配器] HTTP 会话已关闭")
        info("[Hermes适配器] 插件已停止")


# 该类方法都依赖该类实例各种方法，无法拆分