import sys, json, asyncio, websockets
from astrbot.api.event import filter
from astrbot.api.provider import LLMResponse
from astrbot.api.all import Star, Context, AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from .Tools import *
from . import logger
from .napcat_send import NapCatSend
from .message_id import MessageId

class Hermes适配器(Star):
    """中央管理器"""
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        logger.debug("[Hermes适配器] __init__开始")
        super().__init__(context)
        self.config: AstrBotConfig = config
        self.event: list[AiocqhttpMessageEvent|None] = [None]  # 使用列表共享实时变化的event对象
        self.群事件:dict[str, AiocqhttpMessageEvent] = {}
        self.私聊事件:dict[str, AiocqhttpMessageEvent] = {}

        logger.设置info日志(config['其他配置']['info日志'])

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
            logger.error("[Hermes适配器] 获取管理员列表失败，你可在代码中手动配置管理员，错误信息：\n" + str(e))
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
        if not 授权配置['自定义指令前缀'].strip():
            授权配置['自定义指令前缀'] = '/'
        self.自定义指令前缀:str = 授权配置['自定义指令前缀']

        self.转发时贴表情: bool = config['emoji配置']['转发时贴表情']
        self.过滤llm结果: bool = config['脱敏配置']['过滤llm结果']
        self.替换目标: str = config['脱敏配置']['替换目标']
        自动添加token = config['脱敏配置']['自动添加token']

        if 自动添加token:
            config['脱敏配置']['敏感字符列表'].extend([
                连接配置['hermes_token'], 连接配置['NapCat_api_token'], 连接配置['反向HTTP令牌']
            ])

        self.ws服务 = None
        self.ws任务 = None
        self.ws已连接 = False
        self.ws重连延迟 = 1.0
        MessageId.记录消息ID = self.引用唤醒
        self.NapCatSend = NapCatSend(config, self.event)

        # 指令执行 HTTP 服务器配置
        指令配置: dict = config['指令配置']
        self.启用llm指令执行器 = 指令配置['启用llm指令执行器']
        self.启用指令HTTP服务器 = 指令配置['启用指令HTTP服务器']
        if self.启用llm指令执行器 or self.启用指令HTTP服务器:
            from .command_manager import 指令管理器
            self.指令管理器 = 指令管理器(context, self.NapCatSend, config, self.群事件, self.私聊事件)
        else:
            self.指令管理器 = None
        if self.启用指令HTTP服务器:
            from .http_server import 指令执行HTTP服务器
            self._指令HTTP主机 = 指令配置['指令HTTP服务器地址']
            self._指令HTTP端口 = 指令配置['指令HTTP服务器端口']
            self.指令执行HTTP服务器 = 指令执行HTTP服务器(self.指令管理器, self.NapCatSend, config)
        else:
            self.指令执行HTTP服务器 = None

        if self.开启反向HTTP:
            from .reverse_http import ReverseHTTPServer
            self.反向HTTP = ReverseHTTPServer(self.NapCatSend, config)

        if config['脱敏配置']['自动保存']:
            config.save_config()

        self.敏感字符列表: list[str] = config['脱敏配置']['敏感字符列表']

        logger.debug("[Hermes适配器] __init__完成")


    # ========== 消息处理 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    async def 接收消息(self, event: AiocqhttpMessageEvent):
        """监听所有消息（群聊+私聊），存储 event 并转发给 Hermes"""
        if not event.get_message_str():
            # 不处理也不存没有文本的事件
            return

        if not isinstance(event, AiocqhttpMessageEvent):
            return
        raw:dict = dict(event.message_obj.raw_message)
        self.event[0] = event
        群号 = str(raw.get('group_id', ""))
        if 群号:
            if 群号 not in self.群事件:
                self.群事件[群号] = event
        else:
            qq = str(raw.get('user_id', ""))
            if qq not in self.私聊事件:
                self.私聊事件[qq] = event

        转发, data = await self.检查转发到Hermes(event)
        if 转发 and self.处理冲突(event):
            来源 = "群聊" if raw.get('group_id') else "私聊"
            await self.发送ws消息(data)
            if self.转发时贴表情:
                await self.NapCatSend.贴表情(data)
            logger.info(f"[Hermes适配器] 已转发[{用户名(raw)}] 的{来源}消息到 Hermes：{event.message_obj.raw_message.get('raw_message')}")
            return
        logger.debug(f"[Hermes适配器] 转发检测未通过")

    @filter.on_llm_response(priority=sys.maxsize)
    async def llm请求后(self, _, resp: LLMResponse):
        """llm请求后过滤敏感字符"""
        if self.过滤llm结果:
            llm文本 = resp.completion_text
            for 敏感词 in self.敏感字符列表:
                llm文本 = llm文本.replace(敏感词, self.替换目标)
            resp.completion_text = llm文本

    @filter.llm_tool("hermes_agent")
    async def llm工具_hermes_agent(self, event: AiocqhttpMessageEvent, task: str = "") -> str:
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
            if not self.ws已连接:
                return "Hermes Agent 未连接，请稍后再试"
            NapCat事件体 = 构造文本NapCat事件体(event, task)
            await self.发送ws消息(NapCat事件体)
            return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"
        except Exception as e:
            logger.error(f"[Hermes适配器] LLM工具执行失败: {e}", exc_info=True)
            return f"执行失败: {str(e)}"

    # ========== 转发Hermes判断 ==========

    @filter.llm_tool("execute_command")
    async def llm工具_执行指令(self, event: AiocqhttpMessageEvent, command: str = "", args: str = "") -> str:
        """
        执行 AstrBot 框架的插件指令。当用户明确要求执行某个指令时使用。

        Args:
            command(string): 指令名（不含前缀），如 "钓鱼"、"签到"、"状态"
            args(string): 指令参数（可选）
        """
        command = command.strip()
        group_id = event.get_group_id() or ''
        if not command:
            return "请输入 command 参数（指令名）"
        if not isinstance(event, AiocqhttpMessageEvent):
            return "当前平台不支持"
        if not self.指令管理器:
            return "管理员未开启该功能"
        try:
            result = await self.指令管理器.执行指令(
                command=command,
                args=args.strip(),
                user_id=event.get_sender_id(),
                user_name=event.get_sender_name(),
                group_id=group_id,
                event=event
            )
            if result.get('success'):
                parts = []
                if result.get('texts'):
                    parts.append("执行结果:\n" + "\n".join(result['texts']))
                if result.get('images'):
                    parts.append(f"生成了 {len(result['images'])} 张图片")
                sent = result.get('sent', 0)
                if sent:
                    parts.append(f"已发送 {sent} 条消息到群")
                return "\n".join(parts) if parts else "指令执行成功（无输出）"
            else:
                return f"指令执行失败: {result.get('error', '未知错误')}"
        except Exception as e:
            logger.error(f"[Hermes适配器] LLM工具执行指令失败: {e}", exc_info=True)
            return f"执行指令失败: {str(e)}"

    def 处理冲突(self, event: AiocqhttpMessageEvent) -> bool:
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

    async def 检查转发到Hermes(self, event: AiocqhttpMessageEvent) -> tuple[bool, dict]:
        """检查是否通过过滤配置"""
        raw: dict = dict(event.message_obj.raw_message)
        群号 = str(raw.get('group_id', ""))
        qq = str(raw.get('user_id', ""))
        text = 纯文本(raw)
        if 群号:
            if not all判断(self.允许的群组, 群号):
                return False, raw
            if not all判断(self.允许的用户, qq):
                return False, raw
        else:
            if not all判断(self.私聊允许的用户, qq):
                return False, raw
            if self.私聊转发所有消息:
                if text.startswith(self.自定义指令前缀):
                    return await self.指令检查(event, raw, text, qq)
                return True, raw  #每个return True之前都要作指令检查
        if self.引用唤醒 and (message_id := 引用ID(raw)) and MessageId.has(message_id):
            if text.startswith(self.自定义指令前缀):
                return await self.指令检查(event, raw, text, qq)
            return True, raw
        if self.艾特机器人触发 and event.get_self_id() in 艾特ID(raw):
            if text.startswith(self.自定义指令前缀):
                return await self.指令检查(event, raw, text, qq)
            return True, raw
        if text.startswith(self.自定义指令前缀):
            return await self.指令检查(event, raw, text, qq)
        if any(i in text for i in self.触发关键词):
            if text.startswith(self.自定义指令前缀):
                return await self.指令检查(event, raw, text, qq)
            return True, raw
        return False, raw

    async def 指令检查(self, event: AiocqhttpMessageEvent, raw, text, qq) -> tuple[bool, dict]:
        """指令检查"""
        指令文本 =  "/" + text[len(self.自定义指令前缀):]
        if self.开启中文映射 and 指令文本 in 授权命令映射:
            指令文本 = 授权命令映射[指令文本]
        if 指令文本.startswith(f"/approve"):
            if all判断(self.允许approve的用户, qq):
                return True, 构造文本NapCat事件体(event, 指令文本)
            else:
                if self.approve无权限提示:
                    await self.发送文本给NapCat(event, self.approve无权限提示)
                if self.无权限处理方式 == "自动发送/deny拒绝命令":
                    return True, 构造文本NapCat事件体(event, '/deny')
                elif self.无权限处理方式 == "发送自定义拒绝信息给Hermes":
                    return True, 构造文本NapCat事件体(event, self.自定义拒绝信息)
                return False, raw
        elif 指令文本.startswith(f"/deny"):
            if all判断(self.允许deny的用户, qq):
                return True, 构造文本NapCat事件体(event, 指令文本)
            return False, raw
        elif 指令文本.startswith("/"):
            if all判断(self.允许其他指令的用户, qq):
                return True, 构造文本NapCat事件体(event, 指令文本)
            return False, raw
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
                logger.debug(f"[Hermes适配器] 已发送数据到Hermes：{data}")
            except Exception as e:
                logger.error(f"[Hermes适配器] WebSocket 发送失败: {e}", exc_info=True)
                logger.debug(f"[Hermes适配器] 发送失败，原始数据: {data}")
                self.ws已连接 = False

    async def ws连接循环(self):
        """WebSocket 重连循环"""
        while True:
            try:
                await self.连接到ws()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Hermes适配器] WebSocket 连接异常: {e}")

            if self.ws已连接:
                self.ws已连接 = False
                logger.info("[Hermes适配器] WebSocket 断开，准备重连...")

            logger.info(f"[Hermes适配器] 等待 {self.ws重连延迟:.1f}s 后重连...")
            await asyncio.sleep(self.ws重连延迟)

    async def 连接到ws(self):
        """连接到 Hermes WebSocket 并监听消息"""
        头 = {}
        if self.hermes_token:
            头['Authorization'] = f'Bearer {self.hermes_token}'

        logger.info(f"[Hermes适配器] 正在连接到 Hermes: {self.hermes_ws_url}")

        async with websockets.connect(
            self.hermes_ws_url,
            additional_headers=头,
            ping_interval=20,
            ping_timeout=60
        ) as ws:
            self.ws服务 = ws
            self.ws已连接 = True
            self.ws重连延迟 = 1.0

            logger.info("[Hermes适配器] WebSocket 已连接到 Hermes")

            await self.发送ws消息({
                "type": "connect",
                "platform": "qqonebot",
                "self_id": "astrbot",
                "data": {}
            })

            async for 原始消息 in ws:
                try:
                    await self.处理ws消息(原始消息)
                    logger.info("[Hermes适配器] 收到来自Hermes的消息")
                except Exception as e:
                    logger.error(f"[Hermes适配器] 处理 WebSocket 消息失败: {e}", exc_info=True)

    async def 处理ws消息(self, raw):
        data = json.loads(raw)
        msg_type = data.get('type', '')
        echo = data.get('echo', '')

        # 处理 send_message：直接发送文本
        if msg_type == 'send_message':
            group_id = data.get('group_id')
            user_id = data.get('user_id')
            message = data.get('message', '')
            if group_id:
                await self.NapCatSend.发送动作参数到NapCat("send_group_msg", {
                    "group_id": int(group_id), "message": message
                })
            elif user_id:
                await self.NapCatSend.发送动作参数到NapCat("send_private_msg", {
                    "user_id": int(user_id), "message": message
                })
            return

        # ping 回复
        if msg_type == 'ping':
            await self.发送ws消息({"type": "pong", "echo": echo})
            return

        # 其他消息（含 api_request）：原样转发给 NapCat
        logger.debug(f"[Hermes适配器] 转发来自Hermes的消息到NapCat的数据：{data}")
        结果 = await self.NapCatSend.发送data消息到NapCat(data)
        logger.debug(f"[Hermes适配器] 转发来自Hermes的消息到NapCat的结果：{结果}")
        await self.发送ws消息(结果)

    # ========== 生命周期 ==========

    async def initialize(self):
        """异步初始化"""
        logger.debug("[Hermes适配器] initialize开始")
        self.指令管理器.重建指令缓存()
        if self.启用指令HTTP服务器:
            await self.指令执行HTTP服务器.start(self._指令HTTP主机, self._指令HTTP端口)
        if self.开启反向HTTP:
            await self.反向HTTP.start()
        await self.ws开始()
        await asyncio.sleep(0.1)
        if self.消息发送方式 == "框架已有的WebSocket":
            logger.warning("[Hermes适配器] 当前发送消息方式为“框架已有的WebSocket”，请在qq发送任意消息以激活")
        logger.debug("[Hermes适配器] initialize完成")
        logger.info("[Hermes适配器] 初始化完成")

    async def terminate(self):
        """插件终止时清理资源"""
        if self.指令执行HTTP服务器:
            await self.指令执行HTTP服务器.stop()
        if self.开启反向HTTP:
            await self.反向HTTP.stop()
        await self.ws停止()
        if self.NapCatSend.http会话 and not self.NapCatSend.http会话.closed:
            await self.NapCatSend.http会话.close()
            logger.info("[Hermes适配器] HTTP 会话已关闭")
        logger.info("[Hermes适配器] 插件已停止")


# 该类方法都依赖该类实例各种方法，无法拆分

# 开源免费，用户使用自己找茬作死（例如端口填写超出范围），概不考虑