import sys, asyncio
from astrbot.api.event import filter
from astrbot.api.provider import LLMResponse
from astrbot.api.all import Star, Context, AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from .Tools import *
from . import logger
from .napcat_send import NapCatSend
from .message_id import MessageId
from .ws_client import HemresWsClient
from .status import HermesStatus
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
                连接配置['hermes_token'], 连接配置['NapCat_api_token'], 连接配置['反向HTTP令牌'],
                config['指令配置']['http指令服务器token']
            ])

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

        self.ws = HemresWsClient(self.hermes_ws_url, self.hermes_token, self.NapCatSend)

        logger.debug("[Hermes适配器] __init__完成")


    # ========== 消息处理 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def 接收消息(self, event: AiocqhttpMessageEvent):
        """监听所有消息（群聊+私聊），存储 AiocqhttpMessageEvent"""
        if not event.get_message_str():
            # 不处理也不存没有文本的事件
            return

        raw:dict = event.message_obj.raw_message
        self.event[0] = event  #此event可以是任意AiocqhttpMessageEvent
        群号 = str(raw.get('group_id', ""))
        if 群号:
            if 群号 not in self.群事件:
                self.群事件[群号] = event
        else:
            qq = str(raw.get('user_id', ""))
            if qq not in self.私聊事件:
                self.私聊事件[qq] = event

        if not self.ws.ws已连接:
            logger.debug(f"[Hermes适配器] Hermes WebSocket 未连接")
            return

        转发, data = await self.检查转发到Hermes(event)
        if 转发 and self.处理冲突(event):
            来源 = "群聊" if raw.get('group_id') else "私聊"
            await self.ws.发送ws消息(data)
            if self.转发时贴表情:
                if 群号:
                    await self.NapCatSend.贴表情(data)
                else:
                    await self.NapCatSend.戳一戳(raw.get('user_id'))
            logger.info(f"[Hermes适配器] 已转发 [{用户名(raw)}] [{来源}] 消息到 Hermes：{event.message_obj.raw_message.get('raw_message')}")
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
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
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
            if not self.ws.ws已连接:
                return "Hermes Agent 未连接，请稍后再试"
            raw: dict = event.message_obj.raw_message
            群号 = str(raw.get('group_id', ""))
            qq = str(raw.get('user_id', ""))
            if task.startswith((self.自定义指令前缀, "/")):
                return "禁止使用此方式发送指令"
            if 群号:
                if not all判断(self.允许的群组, 群号):
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
                if not all判断(self.允许的用户, qq):
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
            else:
                if not all判断(self.私聊允许的用户, qq):
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
            NapCat事件体 = 构造文本NapCat事件体(event, task)
            await self.ws.发送ws消息(NapCat事件体)
            HermesStatus.LLM工具调用 += 1
            return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"
        except Exception as e:
            logger.error(f"[Hermes适配器] LLM工具执行失败: {e}", exc_info=True)
            return f"执行失败: {str(e)}"

    @filter.llm_tool("execute_command")
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
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
            HermesStatus.指令执行次数 += 1
            if result.get('success'):
                HermesStatus.指令成功 += 1
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
                HermesStatus.指令失败 += 1
                return f"指令执行失败: {result.get('error', '未知错误')}"
        except Exception as e:
            HermesStatus.指令失败 += 1
            logger.error(f"[Hermes适配器] LLM工具执行指令失败: {e}", exc_info=True)
            return f"执行指令失败: {str(e)}"

    @filter.llm_tool("hermes_status")
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def llm工具_hermes_status(self, _: AiocqhttpMessageEvent) -> str:
        """
        查询 Hermes Agent 和适配器的运行状态。

        Returns:
            str: 状态信息，包括连接状态、运行时间、统计信息等
        """
        ws_status = "已连接" if self.ws.ws已连接 else "未连接"
        cmd_count = len(self.指令管理器.处理器缓存) if self.指令管理器 else 0
        group_cached = len(self.群事件)
        private_cached = len(self.私聊事件)

        return (
            f"Hermes 适配器状态:\n"
            f"- WebSocket 连接: {ws_status}\n"
            f"- 已缓存指令: {cmd_count}个\n"
            f"- 已缓存群聊事件: {group_cached}个\n"
            f"- 已缓存私聊事件: {private_cached}个\n"
            f"- 消息发送方式: {self.消息发送方式}\n"
            f"- 指令HTTP服务器: {'开启' if self.启用指令HTTP服务器 else '关闭'}"
        )

    @filter.llm_tool("list_commands")
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def llm工具_list_commands(self, _: AiocqhttpMessageEvent) -> str:
        """
        列出所有可执行的 AstrBot 指令列表。

        Returns:
            str: 指令列表（指令名 + 描述）
        """
        if not self.指令管理器:
            return "管理员未开启指令功能"
        if not self.指令管理器.处理器缓存:
            self.指令管理器.重建指令缓存()

        commands = []
        for name, info in self.指令管理器.处理器缓存.items():
            desc = info.get('description', '无描述')
            admin_tag = " [管理员]" if info.get('is_admin') else ""
            commands.append(f"  • {name}: {desc}{admin_tag}")

        if not commands:
            return "没有找到可用指令"

        return f"可用指令列表 (共{len(commands)}个):\n" + "\n".join(commands)

    @filter.command("hermes状态", alias={"爱马仕状态", "Hermes状态", "hstatus", "Hstatus"})
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def Hermes状态指令(self, _):
        """发送Hermes状态"""
        # 实时状态
        ws状态 = "已连接" if self.ws.ws已连接 else "未连接"
        指令缓存 = len(self.指令管理器.处理器缓存) if self.指令管理器 else 0
        群聊缓存 = len(self.群事件)
        私聊缓存 = len(self.私聊事件)
        http服务器 = "运行中" if self.启用指令HTTP服务器 else "未启用"
        反向http = "运行中" if self.开启反向HTTP else "未启用"
        
        状态信息 = (
            f"=== Hermes 适配器状态 ===\n"
            f"Hermes WebSocket: {ws状态}\n"
            f"消息发送: {'NapCat HTTP' if self.消息发送方式 == 'NapCat Http 服务器' else 'AstrBot WebSocket'}\n"
            f"指令HTTP: {http服务器}\n"
            f"反向HTTP: {反向http}\n"
            f"缓存: {指令缓存}个指令 | {群聊缓存}个群 | {私聊缓存}个私聊\n"
            f"\n{HermesStatus.总结()}"
        )
        yield _.plain_result(状态信息)

    # ========== qq消息过滤 ==========（在此模块即可，不用过度模块化）

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
        raw: dict = event.message_obj.raw_message
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
        if self.艾特机器人触发 and str(raw.get('self_id')) in 艾特ID(raw):
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
        """通过当前event判断群聊或私聊直接发送文本
        此方法依赖当前事件，不能移到NapCatSend模块"""
        raw: dict = event.message_obj.raw_message
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

    # ========== 生命周期 ==========

    async def initialize(self):
        """异步初始化"""
        logger.debug("[Hermes适配器] initialize开始")
        if self.指令管理器:
            self.指令管理器.重建指令缓存()
        if self.启用指令HTTP服务器:
            await self.指令执行HTTP服务器.start(self._指令HTTP主机, self._指令HTTP端口)
        if self.开启反向HTTP:
            await self.反向HTTP.start()
        await self.ws.ws开始()
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
        await self.ws.ws停止()
        if self.NapCatSend.http会话 and not self.NapCatSend.http会话.closed:
            await self.NapCatSend.http会话.close()
            logger.info("[Hermes适配器] HTTP 会话已关闭")
        logger.info("[Hermes适配器] 插件已停止")


# 异步单线程