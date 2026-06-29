import sys, asyncio
from astrbot.api.event import filter
from astrbot.api.provider import LLMResponse
from astrbot.api.all import Star, Context, AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from .Tools import *
from .logger import logger
from .napcat_send import NapCatSend
from .消息发送处理器 import 消息发送处理器
from .message_id import MessageId
from .ws_client import WsClient
from .status import Status


class Hermes适配器(Star):
    """中央管理器"""
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        logger.debug("__init__开始")
        super().__init__(context)
        self.config: AstrBotConfig = config
        self.群事件:dict[str, AiocqhttpMessageEvent] = {}
        self.私聊事件:dict[str, AiocqhttpMessageEvent] = {}
        self._bot = None  # 主动发现的 bot 实例

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
            self.反向HTTP地址 = self.反向HTTP令牌 = ""

        try:
            管理员列表 = context.get_config()["admins_id"]
        except Exception as e:
            logger.error("获取管理员列表失败，你可在代码中手动配置管理员，错误信息：\n" + str(e))
            管理员列表 = []

        def 清理列表(l: list) -> list[str]:
            """去除列表中每个元素的空白字符，并过滤掉空字符串"""
            return list(dict.fromkeys([i.strip() for i in l if i.strip()]))

        def 解析all(l: list[str], ad=True) -> list[str]:
            """解析all和admin"""
            if "all" in l:
                # 保留黑名单条目（/开头），避免 ["all", "/12345"] 时丢失黑名单
                黑名单条目 = [i for i in l if i.startswith('/')]
                return ["all"] + 黑名单条目
            if ad and "admin" in l:
                l.extend(管理员列表)
            return list(dict.fromkeys(l))

        # ========== 过滤配置 ==========
        过滤配置: dict = config['过滤配置']
        self.跳过指令 = 过滤配置['跳过指令']
        if self.跳过指令:
            from astrbot.core.star.star_handler import star_handlers_registry
            from astrbot.core.star.filter.command_group import CommandGroupFilter, CommandFilter
            # 遍历所有注册的处理器获取所有命令，包括别名
            指令列表 = []
            for handler in star_handlers_registry:
                for i in handler.event_filters:
                    if isinstance(i, CommandFilter):
                        指令列表.append(i.command_name)
                        # 获取别名 - 属性名是 alias，类型是 set
                        if hasattr(i, 'alias') and i.alias:
                            指令列表.extend(list(i.alias))
                    elif isinstance(i, CommandGroupFilter):
                        指令列表.append(i.group_name)
            self.所有指令 = set(指令列表)
        # 群组
        raw_groups = 解析all(清理列表(过滤配置['允许的群组']), False)
        self.黑名单群组 = [i[1:] for i in raw_groups if i.startswith('/')]
        self.允许的群组 = [i for i in raw_groups if not i.startswith('/')]
        logger.info(f"解析后 - 允许的群组: {self.允许的群组}")
        logger.info(f"解析后 - 黑名单群组: {self.黑名单群组}")

        # 用户
        raw_users = 解析all(清理列表(过滤配置['允许的用户']))
        self.黑名单用户 = [i[1:] for i in raw_users if i.startswith('/')]
        self.允许的用户 = [i for i in raw_users if not i.startswith('/')]
        logger.info(f"解析后 - 允许的用户: {self.允许的用户}")
        logger.info(f"解析后 - 黑名单用户: {self.黑名单用户}")

        # 私聊用户
        raw_private = 解析all(清理列表(过滤配置['私聊允许的用户']))
        self.私聊黑名单 = [i[1:] for i in raw_private if i.startswith('/')]
        self.私聊允许的用户 = [i for i in raw_private if not i.startswith('/')]
        logger.info(f"解析后 - 私聊允许的用户: {self.私聊允许的用户}")
        logger.info(f"解析后 - 私聊黑名单: {self.私聊黑名单}")
        self.跟随框架唤醒 = 过滤配置['跟随框架唤醒']
        if not self.跟随框架唤醒:
            self.私聊转发所有消息: bool = 过滤配置['私聊转发所有消息']
            self.引用唤醒: bool = 过滤配置['引用唤醒']
            self.艾特机器人触发: bool = 过滤配置['艾特机器人触发']
            self.触发关键词: list[str] = 清理列表(过滤配置['触发关键词'])
            self.触发关键词字典:dict[str,str] = {
                i.replace('-d', '').replace('-s', '').replace('-e', ''): i
                for i in self.触发关键词
            }  #参数映射，触发时照的
            self.同时唤醒处理方式: str = 过滤配置['同时唤醒处理方式']
        else:
            self.私聊转发所有消息 = self.引用唤醒 = self.艾特机器人触发 = False
            self.触发关键词: list[str] = []
            self.同时唤醒处理方式: str = ""

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
        self.回复时发表情包: bool = config['emoji配置']['回复时发表情包']
        self.过滤llm结果: bool = config['脱敏配置']['过滤llm结果']

        # 初始化处理器（配置 + 钩子一体化）
        self.消息发送处理器 = 消息发送处理器(config)

        # 注册回复时发表情包钩子
        if self.回复时发表情包:
            from .napcat_send import 消息钩子
            # 获取 stealer 插件
            from astrbot.core.star import star_map
            self.stealer = None
            for meta in star_map.values():
                if getattr(meta, "name", "") in ("表情包小偷", "astrbot_plugin_stealer") and meta.activated:
                    self.stealer = meta.star_cls
                    break
            消息钩子.发送后(self._回复时发表情包, 优先级=80)

        # 补充连接相关 token 到敏感字符列表
        自动添加token = config['脱敏配置']['自动添加token']
        if 自动添加token:
            self.消息发送处理器.敏感字符列表.extend(
                i for i in
                [
                连接配置['hermes_token'], 连接配置['NapCat_api_token'], 连接配置['反向HTTP令牌'],
                config['指令配置']['http指令服务器token']
            ] if i
            )

        MessageId.记录消息ID = self.引用唤醒
        self.NapCatSend = NapCatSend(config)
        self.set_event = self.NapCatSend.set_event #节省性能，避免每次链式查找

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

        self.ws = WsClient(self.hermes_ws_url, self.hermes_token, self.NapCatSend)
        self.self_id = config['其他配置']['机器人qq'].strip()
        self.ws.机器人qq = str(self.self_id)
        self.启用Hermes连接报告 = config['其他配置']['启用Hermes连接报告']
        if self.启用Hermes连接报告:
            self.ws.开启连接报告 = True
            self.重启命令:str = config['其他配置']['重启Hermes命令']
            self.ws.发送类型 = config['其他配置']['发送目标类型']
            self.ws.目标ID = config['其他配置']['发送目标ID']
        else:
            self.重启命令 = self.发送目标类型 = self.发送目标ID = ""

        self.开启快速授权 = self.消息发送处理器.开启快速授权

        logger.debug("__init__完成")

    # ========== 消息处理 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def 接收消息(self, event: AiocqhttpMessageEvent):
        """监听所有消息（群聊+私聊），存储 AiocqhttpMessageEvent"""
        raw: dict = event.message_obj.raw_message
        self_id = str(raw.get('self_id', ""))
        if self.self_id and str(self_id) != self.self_id:
            logger.debug("检测到配置了机器人qq，但该事件的self_id不匹配，，跳过")
            return
        群号 = str(raw.get('group_id', ""))
        qq = str(raw.get('user_id', ""))
        self.set_event(event)  #此event可以是任意AiocqhttpMessageEvent
        if qq == self_id:
            return
        if self.开启快速授权:
            if raw.get('sub_type') == 'poke':
                if str(raw.get("target_id")) != self_id:
                    return
                if 群号:
                    if MessageId.has_sq(群号) and all判断(self.允许的群组, 群号) and all判断(self.允许的用户, qq) and all判断(self.允许approve的用户, qq):
                        data = 构造文本NapCat事件体(
                            event, '/approve',
                            message_type="group",
                            message_format="array",
                            post_type="message",
                            sub_type="normal",
                            sender={}
                        )
                        await self.ws.发送ws消息(data)
                        logger.info(f"快速授权：群聊戳一戳触发 approve，群号={群号}，用户={qq}")
                        MessageId.cl_sq(群号)
                    return
                else:
                    if MessageId.has_sq(qq) and  all判断(self.私聊允许的用户, qq) and all判断(self.允许approve的用户, qq):
                        data = 构造文本NapCat事件体(
                            event, '/approve',
                            message_type="friend",
                            message_format="array",
                            post_type="message",
                            sub_type="normal",
                            sender={}
                        )
                        await self.ws.发送ws消息(data)
                        logger.info(f"快速授权：私聊戳一戳触发 approve，用户={qq}")
                        MessageId.cl_sq(qq)
                    return

            if raw.get('notice_type') == 'group_msg_emoji_like':
                mid = raw.get('message_id')
                if 群号:
                    if MessageId.eq_sq(mid, 群号) and all判断(self.允许的群组, 群号) and all判断(self.允许的用户, qq) and all判断(self.允许approve的用户, qq):
                        data = 构造文本NapCat事件体(
                            event, '/approve session',
                            message_type="group",
                            message_format="array",
                            post_type="message",
                            sub_type="normal",
                            sender={}
                        )
                        await self.ws.发送ws消息(data)
                        logger.info(f"快速授权：群聊表情回应触发 approve session，群号={群号}，用户={qq}，消息ID={mid}")
                        MessageId.cl_sq(群号)
                    return
                else:
                    if MessageId.eq_sq(mid, qq) and all判断(self.私聊允许的用户, qq) and all判断(self.允许approve的用户, qq):
                        data = 构造文本NapCat事件体(
                            event, '/approve session',
                            message_type="friend",
                            message_format="array",
                            post_type="message",
                            sub_type="normal",
                            sender={}
                        )
                        await self.ws.发送ws消息(data)
                        logger.info(f"快速授权：私聊表情回应触发 approve session，用户={qq}，消息ID={mid}")
                        MessageId.cl_sq(qq)
                    return

        if not (text:=event.get_message_str()):
            pass
            #return

        群号 = str(raw.get('group_id', ""))
        if 群号:
            self.群事件[群号] = event
        else:
            if qq := str(raw.get('user_id', "")):
                self.私聊事件[qq] = event
        if self.跳过指令 and (l:=text.strip().split()) and (l[0] in self.所有指令):
            logger.debug(f"跳过框架指令：{text}")
            return
        if not self.ws.ws已连接:
            logger.debug(f"Hermes WebSocket 未连接")
            return

        转发, data = await self.检查转发到Hermes(event)
        if self.跟随框架唤醒:
            event.set_extra("Hermes唤醒", data)
            return
        if 转发 and self.处理冲突(event):
            来源 = "群聊" if 群号 else "私聊"
            logger.debug(f"转发的事件体：\n{data}")
            await self.ws.发送ws消息(data)
            if self.转发时贴表情:
                if 群号:
                    await self.NapCatSend.贴表情(data, self.消息发送处理器.随机表情())
                else:
                    await self.NapCatSend.戳一戳(raw.get('user_id'))
            logger.info(f"已转发 [{用户名(raw)}] [{来源}] 消息到 Hermes：{event.message_obj.raw_message.get('raw_message')}")
            return
        logger.debug(f"转发检测未通过")

    async def _回复时发表情包(self, 事件, _context):
        """发送后钩子：复用 stealer 的概率+冷却判断，回复时概率发表情包"""
        try:
            群号 = 事件.群号
            qq = 事件.QQ号
            if not 群号 and not qq:
                return

            # 从缓存中取 event
            if 群号:
                event = self.群事件.get(str(群号))
            else:
                event = self.私聊事件.get(str(qq))
            if not event:
                return

            # 提取回复文本给 stealer 分析情绪
            消息 = 事件.消息
            if not 消息:
                return
            if isinstance(消息, str):
                text = 消息
            elif isinstance(消息, list):
                text = "".join(
                    seg.get("data", {}).get("text", "")
                    for seg in 消息
                    if seg.get("type") == "text"
                )
            else:
                return
            if not text.strip():
                return
            if not self.stealer:
                from astrbot.core.star import star_map
                for meta in star_map.values():
                    if getattr(meta, "name", "") == "表情包小偷" and meta.activated:
                        self.stealer = meta.star_cls
                        break

            if not self.stealer:
                logger.warning("回复时发表情，未找到表情包小偷插件")
                Status.发表情包失败 += 1
                return

            stealer = self.stealer
            engine = stealer._emoji_sender_engine

            # 复用 stealer 的概率+冷却判断
            allowed = await engine.resolve_auto_emoji_turn_permission(event)
            if not allowed:
                return

            # 分析情绪
            user_query = ""
            try:
                user_query = event.get_message_str() or ""
            except Exception:
                pass
            emotion = await stealer.smart_emotion_matcher.analyze_and_match_emotion(
                event, text, user_query=user_query
            )
            if emotion:
                sent = await engine.try_send_emoji(event, [emotion], text)
                if sent:
                    Status.发表情包成功 += 1
                else:
                    Status.发表情包失败 += 1
        except Exception as e:
            Status.发表情包失败 += 1
            logger.error(f"[表情包钩子] 执行失败: {e}")

    @filter.on_llm_request(priority=-sys.maxsize)
    async def llm请求前(self, event: AiocqhttpMessageEvent, _):
        """检测是否跟随框架唤醒"""
        if self.跟随框架唤醒 and (data := event.get_extra("Hermes唤醒", False)):
            raw: dict = event.message_obj.raw_message
            群号 = str(raw.get('group_id', ""))
            来源 = "群聊" if 群号 else "私聊"
            await self.ws.发送ws消息(data)
            if self.转发时贴表情:
                if 群号:
                    await self.NapCatSend.贴表情(data, self.消息发送处理器.随机表情())
                else:
                    await self.NapCatSend.戳一戳(raw.get('user_id'))
            logger.info("已跟随框架唤醒")
            event.stop_event()
            logger.info(f"已转发 [{用户名(raw)}] [{来源}] 消息到 Hermes：{event.message_obj.raw_message.get('raw_message')}")
            return

    @filter.on_llm_response(priority=sys.maxsize)
    async def llm请求后(self, _, resp: LLMResponse):
        """llm请求后过滤敏感字符"""
        if self.过滤llm结果:
            处理器 = self.消息发送处理器
            llm文本 = resp.completion_text
            for 敏感词 in 处理器.敏感字符列表:
                llm文本 = llm文本.replace(敏感词, 处理器.替换目标)
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
                if 群号 in self.黑名单群组:
                    return "该群未授权使用Hermes，Agent，请联系管理员"
                if qq in self.黑名单用户:
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
                if not all判断(self.允许的群组, 群号):
                    return "该群未授权使用Hermes，Agent，请联系管理员"
                if not all判断(self.允许的用户, qq):
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
            else:
                if qq in self.私聊黑名单:
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
                if not all判断(self.私聊允许的用户, qq):
                    return "该用户未授权使用Hermes，Agent，请联系管理员"
            NapCat事件体 = 构造文本NapCat事件体(event, task)
            await self.ws.发送ws消息(NapCat事件体)
            Status.LLM工具调用 += 1
            return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"
        except Exception as e:
            logger.error(f"LLM工具执行失败: {e}", exc_info=True)
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
            Status.指令执行次数 += 1
            if result.get('success'):
                Status.指令成功 += 1
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
                Status.指令失败 += 1
                return f"指令执行失败: {result.get('error', '未知错误')}"
        except Exception as e:
            Status.指令失败 += 1
            logger.error(f"LLM工具执行指令失败: {e}", exc_info=True)
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
            f"\n{Status.总结()}"
        )
        yield _.plain_result(状态信息)

    @filter.command("重启爱马仕", alias={"重启Hermes"})
    async def Hermes重启指令(self, event):
        # 立即发送“正在重启”的回复
        await event.send(event.plain_result("🔄 正在重启Hermes…"))
        self.ws.设置重启状态(event)

        # 定义后台执行重启命令的异步函数
        async def _execute_restart():
            try:
                proc = await asyncio.create_subprocess_shell(
                    self.重启命令,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    logger.info(f"重启成功: {stdout.decode()}")
                else:
                    logger.error(f"重启失败: {stderr.decode()}")
                    await event.send(event.plain_result("❌ 重启命令执行失败，请查看控制台"))
            except asyncio.TimeoutError:
                logger.error("重启命令执行超时")
                await event.send(event.plain_result("⚠️ 重启命令执行超时"))
            except Exception as e:
                logger.error(e)
                await event.send(event.plain_result(f"❌ 执行异常: {e}"))

        # 创建后台任务，当前协程立即返回，不等待重启完成
        asyncio.create_task(_execute_restart())

    # ========== qq消息过滤 ==========（在此模块即可，不用过度模块化）

    def 处理冲突(self, event: AiocqhttpMessageEvent) -> bool:
        """处理 LLM 和 Hermes 同时唤醒时的冲突"""
        if self.同时唤醒处理方式 == '只用Hermes':
            logger.info("终止事件，使用hermes")
            event.stop_event()
            return True
        elif self.同时唤醒处理方式 == '都处理':
            if event.is_at_or_wake_command:
                logger.info("已同时唤醒")
            return True
        elif self.同时唤醒处理方式 == '不使用Hermes':
            if event.is_at_or_wake_command:
                logger.info("llm已唤醒，不使用hermes")
                return False
            logger.info("llm未唤醒，使用hermes")
            event.stop_event()
            return True
        return False

    async def 检查转发到Hermes(self, event: AiocqhttpMessageEvent) -> tuple[bool, dict]:
        """检查是否通过过滤配置"""
        raw: dict = dict(event.message_obj.raw_message)
        群号 = str(raw.get('group_id', ""))
        qq = str(raw.get('user_id', ""))
        text = 纯文本(raw)
        logger.debug(f"消息文本：{text}")
        指令前缀 = self.自定义指令前缀
        if 指令前缀 != '/' and text.startswith('/'):
            return False, raw  #防止意外指令被转发
        if 群号:
            if 群号 in self.黑名单群组:
                return False, raw
            if qq in self.黑名单用户:
                return False, raw
            if not all判断(self.允许的群组, 群号):
                return False, raw
            if not all判断(self.允许的用户, qq):
                return False, raw
            if self.跟随框架唤醒:
                if text.startswith(指令前缀):
                    MessageId.cl_sq(群号)
                    return await self.指令检查(event, raw, text, qq)
                return True, raw
        else:
            if qq in self.私聊黑名单:
                return False, raw
            if not all判断(self.私聊允许的用户, qq):
                return False, raw
            if self.跟随框架唤醒:
                if text.startswith(指令前缀):
                    return await self.指令检查(event, raw, text, qq)
                return True, raw
            if self.私聊转发所有消息:
                if text.startswith(指令前缀):
                    MessageId.cl_sq(qq)
                    return await self.指令检查(event, raw, text, qq)
                return True, raw  #每个return True之前都要作指令检查
        if text.startswith(指令前缀):
            return await self.指令检查(event, raw, text, qq)
        if self.引用唤醒 and (message_id := 引用ID(raw)) and MessageId.has(message_id):
            return True, raw
        if self.艾特机器人触发 and str(raw.get('self_id')) in 艾特ID(raw):
            return True, raw
        for i in self.触发关键词:
            logger.debug(f"关键词：{i}")
            logger.debug(f"-s in i ：{'-s' in i}，-d in i：{'-d' in i}")
            if "-s" in i:
                logger.debug(f"命中第一条-s")
                s = i.replace('-s', '').strip()
                需要去除 = False
                if "-d" in s:
                    s = s.replace('-d', '').strip()
                    需要去除 = True
                logger.debug(f"处理后s：{s}")
                if text.startswith(s):
                    logger.debug(f"触发前缀{s}")
                    if 需要去除: #去除消息文本开头的s，实际上触发的是s而不是i
                        return True, 去除关键词(raw, s, 's')
                    return True, raw
            elif '-e' in i:
                logger.debug(f"命中第二条-e")
                s = i.replace('-e', '').strip()
                需要去除 = False
                if '-d' in s:
                    需要去除 = True
                    s = s.replace('-d', '').strip()
                logger.debug(f"处理后s：{s}")
                if text.endswith(s):
                    logger.debug(f"触发后缀{s}")
                    if 需要去除: #去除消息文本末尾的s，实际上触发的是s而不是i
                        return True, 去除关键词(raw, s, 'e')
                    return True, raw
            elif '-d' in i:
                logger.debug(f"命中第三条-d")
                s = i.replace('-d', '').strip()
                logger.debug(f"处理后s：{s}")
                if s in text:
                    logger.debug(f"触发含有{s}")
                    return True, 去除关键词(raw, s)
            elif i in text:
                logger.debug(f"命中第四条")
                logger.debug(f"触发含有{i}")
                return True, raw
        return False, raw

    async def 指令检查(self, event: AiocqhttpMessageEvent, raw:dict, text:str, qq:str) -> tuple[bool, dict]:
        """指令检查"""
        艾特列表 = 艾特ID(raw)
        引用消息ID = 引用ID(raw)
        selfID = str(raw.get('self_id'))
        if 艾特列表 and str(raw.get('self_id')) not in 艾特列表:
            logger.debug("不是艾特机器人的消息，跳过")
            return False, raw
        if 引用消息ID and selfID != 引用消息ID:
            logger.debug("不是回复机器人的消息，跳过")
            return False, raw
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

    # ========== Bot 实例发现 ==========

    async def _discover_bot_instance(self):
        """从 AstrBot 上下文主动发现 OneBot bot 实例"""
        platform_manager = getattr(self.context, "platform_manager", None)
        if not platform_manager:
            logger.warning("无法获取 platform_manager")
            return None

        get_insts = getattr(platform_manager, "get_insts", None)
        if not callable(get_insts):
            logger.warning("platform_manager 没有 get_insts 方法")
            return None

        platforms = get_insts()
        if not platforms:
            logger.warning("未发现任何平台实例")
            return None

        # logger.info(f"发现 {len(platforms)} 个平台实例")

        for platform in platforms:
            bot_client = None
            # 尝试多种方式获取 bot client
            get_client = getattr(platform, "get_client", None)
            if callable(get_client):
                bot_client = get_client()
            if not bot_client:
                bot_client = getattr(platform, "bot", None)
            if not bot_client:
                bot_client = getattr(platform, "client", None)

            # 检查是否是 OneBot (有 call_action 方法)
            if bot_client and hasattr(bot_client, "call_action"):
                if type(bot_client).__name__ != "CQHttp":
                    continue
                logger.info(f"主动发现 NapCat（OneBot） 实例: {type(bot_client).__name__}")
                return bot_client

        logger.warning("未发现可用的 OneBot 实例")
        return None

    # ========== 生命周期 ==========

    async def initialize(self):
        """异步初始化"""
        logger.debug("initialize开始")
        if self.指令管理器:
            self.指令管理器.重建指令缓存()
        if self.启用指令HTTP服务器:
            await self.指令执行HTTP服务器.start(self._指令HTTP主机, self._指令HTTP端口)
        if self.开启反向HTTP:
            await self.反向HTTP.start()

        if self.消息发送方式 == "框架已有的WebSocket":
            bot = await self._discover_bot_instance()
            if not bot:
                logger.warning("未获取到NapCat bot实例当前发送消息方式为框架已有的WebSocket，请在qq发送任意消息以激活")
            else:
                from .aiocqhttpevent import AiocqhttpEvent
                event = AiocqhttpEvent(bot)
                from typing import cast
                event = cast(AiocqhttpMessageEvent, cast(object, event))
                self.set_event(event)

        await asyncio.sleep(0.1)
        await self.ws.ws开始()

        logger.debug("initialize完成")
        logger.info("初始化完成")

    async def terminate(self):
        """插件终止时清理资源"""
        if self.指令执行HTTP服务器:
            await self.指令执行HTTP服务器.stop()
        if self.开启反向HTTP:
            await self.反向HTTP.stop()
        await self.ws.ws停止()
        if self.NapCatSend.http会话 and not self.NapCatSend.http会话.closed:
            await self.NapCatSend.http会话.close()
            logger.info("HTTP 会话已关闭")
        logger.info("插件已停止")


# 异步单线程
