"""
指令管理模块

负责指令缓存构建、指令查找/验证/分类、指令执行、LLM 工具注册。
"""
import time
import copy
import json
from typing import Dict, Optional, Tuple, Any
from astrbot.api.all import (
    logger, Plain, Image, Json,
    AstrBotMessage, MessageMember, MessageType
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata

# 指令分类关键词映射
COMMAND_CATEGORY_MAP = {
    '音乐': ['点歌', 'play', '搜歌', 'song', 'meting', 'kugou', 'kuwo', 'netease', 'qqmusic', 'tencent', 'cloudmusic', '网易', '酷狗', '酷我', 'QQ', '腾讯'],
    '宠物': ['宠物', '领养', '喂食', '玩耍', '散步', '进化', '技能', '背包', '商店', '购买', '装备', '对决', '审判', '偷', '丢弃'],
    '好感度': ['好感', '查看好感', '查询好感', '设置好感', '重置好感', '好感排行', '负好感', '印象', '设置印象'],
    '群管理': ['群规', '添加群规', '删除群规', '设置群规', '群拉黑', '群解除拉黑', '屏蔽', '取消屏蔽', '拉黑', '解除拉黑', '黑名单'],
    '系统': ['状态', '系统状态', '运行状态', '模型', '当前模型', '切换模型', '重启', '更新', '备份', '恢复'],
    '生图': ['画图', '生图', '图片', '切换生图', '禁用生图', '启用生图', '特权生图'],
    '表情包': ['表情', 'meme', '表情包', '表情列表', '表情启用', '表情禁用'],
    '分析': ['群分析', '分析设置', '自然分析'],
    '其他': []
}


class CommandManager:
    """指令管理器 - 缓存、查找、验证、执行"""

    def __init__(self, adapter):
        self._adapter = adapter
        self.处理器缓存: Dict[str, Dict] = {}
        self.别名到指令: Dict[str, str] = {}
        self._所有指令集合: set = set()

    # ========== 缓存管理 ==========

    def rebuild_cache(self):
        """重建指令处理器缓存"""
        context = self._adapter.context
        self.处理器缓存.clear()
        self.别名到指令.clear()

        try:
            all_plugins = context.get_all_stars()
            all_plugins = [p for p in all_plugins if p.activated]
        except Exception as e:
            logger.error(f"[Hermes适配器] 获取插件列表失败: {e}", exc_info=True)
            return

        if not all_plugins:
            return

        skip_plugins = {"astrbot", "hermes_adapter"}
        module_to_plugin = {}
        for plugin in all_plugins:
            name = getattr(plugin, "name", "未知插件")
            module_path = getattr(plugin, "module_path", None)
            if name in skip_plugins or not module_path:
                continue
            module_to_plugin[module_path] = (plugin, name)

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue

            plugin_info = module_to_plugin.get(handler.handler_module_path)
            if not plugin_info:
                continue

            plugin_inst, plugin_name = plugin_info
            cmd_name = None
            aliases = []
            description = handler.desc or "无描述"
            is_admin = False

            for f in handler.event_filters:
                if isinstance(f, CommandFilter):
                    cmd_name = f.command_name
                    if hasattr(f, 'alias') and f.alias:
                        aliases = list(f.alias) if isinstance(f.alias, (set, list)) else []
                elif isinstance(f, CommandGroupFilter):
                    cmd_name = f.group_name
                elif isinstance(f, PermissionTypeFilter):
                    is_admin = True

            if cmd_name:
                if cmd_name.startswith("/"):
                    cmd_name = cmd_name[1:]
                self.处理器缓存[cmd_name] = {
                    "command": cmd_name,
                    "description": description,
                    "plugin": plugin_name,
                    "aliases": aliases,
                    "is_admin": is_admin,
                    "handler": handler,
                    "module_path": handler.handler_module_path
                }
                for alias in aliases:
                    if alias.startswith("/"):
                        alias = alias[1:]
                    self.别名到指令[alias] = cmd_name

        # 构建快速查找集合
        self._所有指令集合 = set()
        for name in self.处理器缓存:
            self._所有指令集合.add(name.lower())
        for alias in self.别名到指令:
            self._所有指令集合.add(alias.lower())

        logger.info(f"[Hermes适配器] 已缓存 {len(self.处理器缓存)} 个指令处理器")

    def 是框架指令(self, text: str) -> bool:
        """判断文本是否为框架指令（空格分割后第一个词在指令集合中）"""
        if not text:
            return False
        parts = text.strip().split()
        first = parts[0].lower() if parts else ''
        return first in self._所有指令集合

    def check_allowed(self, command: str) -> Tuple[bool, str]:
        """检查指令是否允许执行"""
        if command.startswith('/'):
            command = command[1:]
        黑名单 = self._adapter.指令黑名单
        白名单 = self._adapter.指令白名单
        if 黑名单 and command in 黑名单:
            return False, f'指令 {command} 在黑名单中'
        if 白名单 and command not in 白名单:
            return False, f'指令 {command} 不在白名单中'
        return True, '可以执行'

    def resolve_command(self, command: str) -> Optional[Dict]:
        """通过指令名或别名查找处理器信息"""
        if command.startswith('/'):
            command = command[1:]
        actual = self.别名到指令.get(command, command)
        return self.处理器缓存.get(actual)

    def categorize_commands(self, category_filter: str = "") -> Dict[str, list]:
        """将指令按分类整理"""
        result: Dict[str, list] = {}
        for name, info in self.处理器缓存.items():
            aliases = info['aliases']
            desc = info['description']
            matched = '其他'
            for cat, keywords in COMMAND_CATEGORY_MAP.items():
                if any(kw in name or kw in desc for kw in keywords):
                    matched = cat
                    break
                if any(kw in alias for alias in aliases for kw in keywords):
                    matched = cat
                    break
            if category_filter and matched != category_filter:
                continue
            if matched not in result:
                result[matched] = []
            usage = f"{name} (别名: {', '.join(aliases[:3])})" if aliases else name
            result[matched].append({
                'name': name, 'description': desc, 'usage': usage,
                'aliases': aliases, 'plugin': info['plugin'],
                'is_admin': info['is_admin'], 'category': matched
            })
        return result

    # ========== 指令执行 ==========

    async def execute_command(self, command: str, args: str = '',
                              user_id: str = 'hermes_agent', user_name: str = 'Hermes Agent',
                              group_id: str = '') -> Dict[str, Any]:
        """
        执行 AstrBot 指令。

        Returns:
            {'texts': [...], 'images': [...], 'sent_messages': N, 'success': bool, 'error': str}
        """
        # 权限检查
        allowed, reason = self.check_allowed(command)
        if not allowed:
            return {'texts': [], 'images': [], 'success': False, 'error': reason}

        if not self.处理器缓存:
            self.rebuild_cache()

        handler_info = self.resolve_command(command)
        if not handler_info:
            available = list(self.处理器缓存.keys())[:20]
            return {'texts': [], 'images': [], 'success': False,
                    'error': f'未找到指令: {command}。可用指令: {", ".join(available)}'}

        return await self._do_execute(handler_info, args, user_id, user_name, group_id)

    async def _do_execute(self, handler_info: Dict, args: str,
                          user_id: str, user_name: str, group_id: str) -> Dict[str, Any]:
        """内部执行指令"""
        try:
            handler_meta = handler_info['handler']
            cmd_name = handler_info['command']
            message_str = f"{cmd_name} {args}" if args else cmd_name

            adapter = self._adapter
            cached_event = adapter.群组事件.get(group_id) if group_id else adapter.私聊事件.get(user_id)

            if cached_event:
                event_obj = copy.copy(cached_event)
                event_obj.message_str = message_str
                event_obj.message_obj = self._build_astrbot_message(
                    group_id=group_id, self_id=cached_event.message_obj.self_id,
                    user_id=user_id, user_name=user_name,
                    session_id=cached_event.session_id, message_str=message_str
                )
            else:
                logger.warning(f"[Hermes适配器] 群 {group_id} 没有存储的 event，使用模拟对象")
                event_obj = self._build_simulated_event(message_str, group_id, user_id, user_name)
                if isinstance(event_obj, dict):
                    return event_obj

            text_results = []
            image_results = []
            sent_messages = []
            logger.info(f"[Hermes适配器] 开始执行指令: {cmd_name}, 参数: {args}")

            try:
                handler_result = handler_meta.handler(event_obj)
                count = 0

                if hasattr(handler_result, '__aiter__'):
                    async for result in handler_result:
                        count += 1
                        if result is not None:
                            if group_id:
                                try:
                                    await self._send_result_to_group(int(group_id), result, sent_messages)
                                except Exception as e:
                                    logger.error(f"[Hermes适配器] OneBot 发送失败: {e}", exc_info=True)
                            self._collect_result(result, text_results, image_results)
                else:
                    result = await handler_result
                    count = 1
                    if result is not None:
                        if group_id:
                            try:
                                await self._send_result_to_group(int(group_id), result, sent_messages)
                            except Exception as e:
                                logger.error(f"[Hermes适配器] OneBot 发送失败: {e}", exc_info=True)
                        self._collect_result(result, text_results, image_results)

                logger.info(f"[Hermes适配器] 执行完成，共 {count} 个结果")
            except TypeError as e:
                logger.warning(f"[Hermes适配器] 异步生成器失败，尝试同步调用: {e}")
                result = await handler_meta.handler(event_obj)
                if result is not None:
                    self._collect_result(result, text_results, image_results)
            except Exception as e:
                logger.error(f"[Hermes适配器] 执行指令异常: {e}", exc_info=True)

            return {'texts': text_results, 'images': image_results,
                    'sent_messages': len(sent_messages), 'success': True}
        except Exception as e:
            logger.error(f"[Hermes适配器] 内部执行指令失败: {e}", exc_info=True)
            return {'texts': [], 'images': [], 'success': False, 'error': str(e)}

    # ========== 结果发送 ==========

    async def _send_result_to_group(self, group_id: int, result, sent: list):
        """将指令执行结果通过 OneBot 发送到群"""
        if not hasattr(result, 'chain') or not result.chain:
            return
        adapter = self._adapter
        onebot = adapter.onebot_client
        emoji_mgr = adapter.emoji_manager

        for component in result.chain:
            msg_id = None
            if isinstance(component, Json):
                data = component.data if hasattr(component, 'data') else {}
                if data:
                    resp = await onebot.send_group_cq(group_id, [{"type": "json", "data": {"data": json.dumps(data)}}])
                    sent.append(resp)
                    msg_id = resp.get("data", {}).get("message_id") if isinstance(resp, dict) else None
                    emoji_mgr.记录消息id(msg_id)
                    if emoji_mgr.回复消息贴表情:
                        await emoji_mgr.贴表情(onebot, msg_id)
                    logger.debug(f"[Hermes适配器] 已通过 OneBot 发送 JSON, message_id={msg_id}")
            elif hasattr(component, 'text') and component.text:
                resp = await onebot.send_group_text(group_id, component.text)
                sent.append(resp)
                msg_id = resp.get("data", {}).get("message_id") if isinstance(resp, dict) else None
                emoji_mgr.记录消息id(msg_id)
                if emoji_mgr.回复消息贴表情:
                    await emoji_mgr.贴表情(onebot, msg_id)
                logger.debug(f"[Hermes适配器] 已通过 OneBot 发送文本, message_id={msg_id}")
            elif isinstance(component, Image):
                if hasattr(component, 'url') and component.url:
                    resp = await onebot.send_group_cq(group_id, [{"type": "image", "data": {"file": component.url}}])
                    sent.append(resp)
                    msg_id = resp.get("data", {}).get("message_id") if isinstance(resp, dict) else None
                    emoji_mgr.记录消息id(msg_id)
                    if emoji_mgr.回复消息贴表情:
                        await emoji_mgr.贴表情(onebot, msg_id)
                    logger.debug(f"[Hermes适配器] 已通过 OneBot 发送图片, message_id={msg_id}")

    @staticmethod
    def _collect_result(result, texts: list, images: list):
        """收集执行结果中的文本和图片"""
        if not hasattr(result, 'chain') or not result.chain:
            return
        for component in result.chain:
            if hasattr(component, 'text') and component.text:
                texts.append(str(component.text))
            elif isinstance(component, Image):
                if hasattr(component, 'url') and component.url:
                    images.append(str(component.url))

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

    def _build_simulated_event(self, message_str, group_id, user_id, user_name):
        """当没有缓存 event 时，构建模拟事件"""
        adapter = self._adapter
        qq_platform = None
        for platform in adapter.context.platform_manager.platform_insts:
            if hasattr(platform, 'get_client'):
                qq_platform = platform
                break
        if not qq_platform:
            return {'texts': [], 'images': [], 'success': False, 'error': '未找到 QQ 平台适配器'}

        bot_instance = qq_platform.get_client()
        meta = qq_platform.meta()
        astrbot_msg = self._build_astrbot_message(
            group_id=group_id, self_id=str(meta.id),
            user_id=user_id, user_name=user_name,
            session_id=f"group_{group_id}" if group_id else f"hermes_{user_id}",
            message_str=message_str
        )
        return AiocqhttpMessageEvent(
            message_str=message_str, message_obj=astrbot_msg,
            platform_meta=meta, session_id=astrbot_msg.session_id, bot=bot_instance
        )
