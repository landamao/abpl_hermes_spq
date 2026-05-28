import copy, time
from astrbot.api.all import (
    logger, Plain, Image, MessageMember, MessageType, AstrBotMessage
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata
from .napcat_send import NapCatSend
class 指令管理器:
    """指令管理器 - 缓存、查找、验证、执行"""

    def __init__(self, context, napcat_send:NapCatSend, config: dict, 群事件, 私聊事件):
        self.context = context
        self.napcat_send = napcat_send
        self.config = config
        self.群事件:dict[str, AiocqhttpMessageEvent] = 群事件
        self.私聊事件:dict[str, AiocqhttpMessageEvent] = 私聊事件

        self.处理器缓存: dict[str, dict] = {}
        self.别名到指令: dict[str, str] = {}
        self.所有指令集合: set = set()
        try:
            self.指令前缀 = tuple(context.get_config()["wake_prefix"])[0]
        except Exception as e:
            logger.error(f"获取指令前缀失败，你可在代码里手动设置，使用默认值 '/': {e}")
            self.指令前缀 = "/"

        # 指令配置
        指令配置: dict = config['指令配置']
        self.指令白名单: list[str] = [i.strip() for i in 指令配置['指令白名单'] if i.strip()]
        if "all" in self.指令白名单:
            self.指令白名单 = ["all"]
        self.指令黑名单: list[str] = [i.strip() for i in 指令配置['指令黑名单'] if i.strip()]
        if "all" in self.指令黑名单:
            self.指令黑名单 = ["all"]

    # ========== 缓存管理 ==========

    def 重建指令缓存(self):
        """重建指令处理器缓存"""
        self.处理器缓存.clear()
        self.别名到指令.clear()

        try:
            所有插件 = self.context.get_all_stars()
            所有插件 = [插件 for 插件 in 所有插件 if 插件.activated]
        except Exception as e:
            logger.error(f"获取插件列表失败: {e}", exc_info=True)
            return

        if not 所有插件:
            return

        跳过插件 = {"astrbot", "Hermes适配器"}
        模块到插件 = {}
        for 插件 in 所有插件:
            指令名 = getattr(插件, "name", "未知插件")
            模块路径 = getattr(插件, "module_path", None)
            if 指令名 in 跳过插件 or not 模块路径:
                continue
            模块到插件[模块路径] = (插件, 指令名)

        for 处理器 in star_handlers_registry:
            if not isinstance(处理器, StarHandlerMetadata):
                continue

            插件信息 = 模块到插件.get(处理器.handler_module_path)
            if not 插件信息:
                continue

            插件实例, 指令名 = 插件信息
            指令名 = None
            别名 = []
            description = 处理器.desc or "无描述"
            管理员权限 = False

            for i in 处理器.event_filters:
                if isinstance(i, CommandFilter):
                    指令名 = i.command_name
                    if hasattr(i, 'alias') and i.alias:
                        别名 = list(i.alias) if isinstance(i.alias, (set, list)) else []
                elif isinstance(i, CommandGroupFilter):
                    指令名 = i.group_name
                elif isinstance(i, PermissionTypeFilter):
                    管理员权限 = True

            if 指令名:
                if 指令名.startswith("/"):
                    指令名 = 指令名[1:]
                self.处理器缓存[指令名] = {
                    "command": 指令名,
                    "description": description,
                    "plugin": 指令名,
                    "aliases": 别名,
                    "is_admin": 管理员权限,
                    "handler": 处理器,
                    "module_path": 处理器.handler_module_path
                }
                for alias in 别名:
                    if alias.startswith("/"):
                        alias = alias[1:]
                    self.别名到指令[alias] = 指令名

        # 构建快速查找集合
        self.所有指令集合 = set()
        for 指令名 in self.处理器缓存:
            self.所有指令集合.add(指令名.lower())
        for alias in self.别名到指令:
            self.所有指令集合.add(alias.lower())

        logger.info(f"已缓存 {len(self.处理器缓存)} 个指令处理器")

    def 指令存在(self, text: str) -> bool:
        """判断文本是否为框架指令"""
        if not text:
            return False
        parts = text.strip().split()
        first = parts[0].lower() if parts else ''
        return first in self.所有指令集合

    def 指令权限检查(self, command: str) -> tuple[bool, str]:
        """检查指令是否允许执行"""
        if command.startswith('/'):
            command = command[1:]
        if self.指令黑名单:
            if self.指令黑名单[0] == "all" or command in self.指令黑名单:
                return False, f'指令 {command} 在黑名单中'
        if self.指令白名单:
            if self.指令白名单[0] == "all" or command in self.指令白名单:
                return True, '可以执行'
            else:
                return False, f'指令 {command} 不在白名单中'
        else:
            return False, f'未配置指令白名单，所有指令不可执行，请配置指令或配置为all'

    def 查找处理器信息(self, command: str) -> dict:
        """通过指令名或别名查找处理器信息"""
        if command.startswith('/'):
            command = command[1:]
        actual = self.别名到指令.get(command, command)
        return self.处理器缓存.get(actual)

    # ========== 指令执行 ==========

    async def 执行指令(
        self,
        command: str,
        args: str = '',
        user_id: str = 'hermes_agent',
        user_name: str = 'Hermes Agent',
        group_id: str = '',
        event: 'AiocqhttpMessageEvent | None' = None
    ) -> dict:
        """
        执行 AstrBot 指令，通过 NapCatSend 发送结果。

        Args:
            command: 指令名
            args: 参数
            user_id: 执行用户 ID
            user_name: 执行用户名
            group_id: 群号（为空则私聊）
            event: 当前 event（可选，用于获取 bot 实例等）

        Returns:
            {'texts': [...], 'images': [...], 'sent': N, 'success': bool, 'error': str}
        """
        # 权限检查
        允许, 理由 = self.指令权限检查(command)
        if not 允许:
            return {'texts': [], 'images': [], 'other': [], 'sent': 0, 'success': False, 'error': 理由}

        if not self.处理器缓存:
            self.重建指令缓存()

        处理器信息 = self.查找处理器信息(command)
        if not 处理器信息:
            available = list(self.处理器缓存.keys())[:20]
            return {'texts': [], 'images': [], 'other': [], 'sent': 0, 'success': False,
                    'error': f'未找到指令: {command}。可用指令: {", ".join(available)}'}
        if 处理器信息['is_admin']:
            # 管理员指令一刀切拒绝，避免未知风险
            return {'texts': [], 'images': [], 'other': [], 'sent': 0, 'success': False, 'error': "该指令需要管理员权限，不允许通过此方法执行，请联系管理员手动执行"}

        return await self._执行指令(处理器信息, args, user_id, user_name, group_id, event)

    async def _执行指令(
        self,
        处理器信息: dict,
        args: str,
        user_id: str,
        user_name: str,
        group_id: str,
        event: AiocqhttpMessageEvent | None
    ) -> dict:
        """内部执行指令"""
        try:
            handler_meta = 处理器信息['handler']
            cmd_name = 处理器信息['command']
            message_str = f"{self.指令前缀}{cmd_name} {args}" if args else f"/{cmd_name}"

            # 获取 event：优先用传入的，其次从 NapCatSend 的 event 列表取
            # if event is None:
            #     event = self.napcat_send.evnet[0]
            # 这个任意的event不能随便用

            if group_id:
                if group_id in self.群事件:
                    event = self.群事件[group_id]
            else:
                if user_id in self.私聊事件:
                    event = self.私聊事件[user_id]

            if event is None:
                return {
                    "提示": "执行失败",
                    'texts': [], 'images': [], 'other': [], 'sent': 0,
                    'success': False, 'error': '没有可用的 event 对象'
                }

            # 构建执行用的 event（浅拷贝，替换消息内容）
            exec_event = copy.copy(event)
            exec_event.message_str = message_str
            exec_event.message_obj = self._build_astrbot_message(
                group_id=group_id or event.get_group_id() or '',
                self_id=event.get_self_id(),
                user_id=user_id,
                user_name=user_name,
                session_id=event.session_id,
                message_str=message_str
            )

            # 执行指令，边产出边发送
            text_results: list[str] = []
            image_results: list[str] = []
            other_results: list[str] = []
            sent_count = 0

            logger.info(f"开始执行指令: {cmd_name}, 参数: {args}")

            try:
                handler_result = handler_meta.handler(exec_event)

                if hasattr(handler_result, '__aiter__'):
                    async for result in handler_result:
                        if result is not None:
                            self._extract_content(result, text_results, image_results, other_results)
                            if group_id:
                                try:
                                    发送结果 = await self._发送结果(group_id, result)
                                    if 发送结果:
                                        sent_count += 1
                                except Exception as e:
                                    logger.error(f"发送指令结果失败: {e}", exc_info=True)
                else:
                    result = await handler_result
                    if result is not None:
                        self._extract_content(result, text_results, image_results, other_results)
                        if group_id:
                            try:
                                发送结果 = await self._发送结果(group_id, result)
                                if 发送结果:
                                    sent_count += 1
                            except Exception as e:
                                logger.error(f"发送指令结果失败: {e}", exc_info=True)

            except TypeError as e:
                try:
                    logger.warning(f"异步生成器失败，尝试同步调用: {e}")
                    result = await handler_meta.handler(exec_event)
                    if result is not None:
                        self._extract_content(result, text_results, image_results, other_results)
                        if group_id:
                            try:
                                发送结果 = await self._发送结果(group_id, result)
                                if 发送结果:
                                    sent_count += 1
                            except Exception as e:
                                logger.error(f"发送指令结果失败: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"执行指令异常: {e}", exc_info=True)
                    return {
                        "提示": "执行异常",
                        'success': False,
                        'texts': text_results, 'images': image_results, 'other': other_results,
                        'sent': 0,  'error': f'执行异常: {str(e)}'
                    }
            except Exception as e:
                logger.error(f"执行指令异常: {e}", exc_info=True)
                return {
                    "提示": "执行异常",
                    'success': False,
                    'texts': text_results, 'images': image_results, 'other': other_results,
                    'sent': 0, 'error': f'执行异常: {str(e)}'
                }

            logger.info(f"指令执行完成: {cmd_name}, 发送 {sent_count} 个结果")

            return {
                "提示": "执行成功，若有结果则已发送",
                'success': True,
                'texts': text_results,
                'images': image_results,
                'other': other_results,
                'sent': sent_count
            }

        except Exception as e:
            logger.error(f"内部执行指令失败: {e}", exc_info=True)
            return {
                "提示": "执行失败",
                'success': False,
                'texts': [], 'images': [], 'other': [], 'sent': 0, 'error': str(e)
            }

    async def _发送结果(self, group_id: str, result) -> dict:
        """通过 NapCatSend.发送框架消息链到NapCat 发送结果"""
        if not hasattr(result, 'chain') or not result.chain:
            logger.debug(f"结果 chain 为空，跳过发送")
            return {}

        logger.debug(f"发送指令结果到群 {group_id}，chain 长度: {len(result.chain)}")

        发送结果 = await self.napcat_send.发送框架消息链到NapCat(
            消息链=result.chain,
            类型="群聊",
            ID=str(group_id)
        )

        if 发送结果.get('status') == 'failed':
            logger.error(f"NapCat 发送失败: {发送结果}")

        return 发送结果

    @staticmethod
    def _extract_content(result, texts: list, images: list, other_results):
        """从结果中提取文本和图片"""
        if not hasattr(result, 'chain') or not result.chain:
            return
        for 组件 in result.chain:
            if isinstance(组件, Plain) and 组件.text:
                texts.append(组件.text)
            elif isinstance(组件, Image):
                if hasattr(组件, 'url') and 组件.url:
                    images.append(str(组件.url))
            else:
                other_results.append("[其他结果]")


    # ========== 模拟事件构建 ==========

    @staticmethod
    def _build_astrbot_message(group_id, self_id, user_id, user_name, session_id, message_str):
        msg = AstrBotMessage()
        msg.group_id = group_id
        msg.self_id = self_id
        msg.sender = MessageMember(user_id=user_id, nickname=user_name)
        msg.type = MessageType.GROUP_MESSAGE
        msg.session_id = session_id
        msg.message_id = str(int(time.time() * 1000) % 2147483647)
        msg.message = [Plain(text=message_str)]
        msg.message_str = message_str
        msg.raw_message = {}
        msg.timestamp = int(time.time())
        return msg
