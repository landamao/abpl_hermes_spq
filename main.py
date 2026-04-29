"""
Hermes Agent 适配器插件 - WebSocket 版本

实现 AstrBot 与 Hermes Agent 的双向通信：
- AstrBot → Hermes: 通过 WebSocket 连接到 Hermes 反向 WS 服务器
- Hermes → AstrBot: 接收 Hermes 指令请求，通过 HTTP API 执行

模块结构:
- command_cache.py  : 指令缓存（构建/查找/验证）
- onebot_api.py     : OneBot API 调用（发送消息/处理请求）
- message_handler.py: 消息处理（转发判断/事件构造）
- http_server.py    : HTTP 服务器（API 端点/指令执行）
- ws_client.py      : WebSocket 客户端（连接/收发消息）
"""
import asyncio
import time
import aiohttp
from typing import Dict
from astrbot.api.event import filter
from astrbot.api.all import (
    Star, Context, AstrBotConfig, logger, Reply
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from .command_cache import build_command_cache, build_all_commands_set, check_command_allowed, resolve_command, categorize_commands
from .message_handler import should_forward, build_onebot_event
from .http_server import start_http_server, stop_http_server, execute_command
from .ws_client import ws_loop, ws_send
from .aiocqhttp_patch import patch_aiocqhttp

class Hermes适配器(Star):
    """Hermes Agent 适配器 - WebSocket 版本"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        patch_aiocqhttp()
        def 清理列表(列表):
            return [i.strip() for i in 列表 if i.strip()]

        # ========== 配置项 ==========
        # 读取各分类配置
        连接配置 = config.get('connection', {})
        http配置 = config.get('http_server', {})
        过滤配置 = config.get('message_filter', {})
        冲突配置 = config.get('conflict_mode', {})
        approve配置 = config.get('approve_deny', {})
        指令配置 = config.get('command_filter', {})

        # WebSocket 连接到 Hermes
        self.hermes_ws_链接 = 连接配置.get('hermes_ws_url', 'ws://127.0.0.1:6701')
        self.hermes_访问令牌 = 连接配置.get('hermes_access_token', '')

        # OneBot API 地址
        self.onebot_api_地址 = 连接配置.get('onebot_api_url', 'http://127.0.0.1:5700')
        self.onebot_api_token = 连接配置.get('onebot_api_token', '')

        # HTTP API 服务器
        self.启用_http_服务器 = http配置.get('enable_http_server', True)
        self.http_服务器_地址 = http配置.get('http_server_addr', '0.0.0.0:8567')
        # 解析 host:port
        if ':' in str(self.http_服务器_地址):
            parts = str(self.http_服务器_地址).rsplit(':', 1)
            self.http_服务器_主机 = parts[0]
            self.http_服务器_端口 = int(parts[1])
        else:
            self.http_服务器_主机 = '0.0.0.0'
            self.http_服务器_端口 = int(self.http_服务器_地址)
        self.http_服务器_令牌 = http配置.get('http_server_token', '')

        # 消息过滤配置
        self.触发关键词 = 过滤配置.get('trigger_keywords', ['纳西妲', 'hermes', 'Hermes'])
        self.触发艾特机器人 = 过滤配置.get('trigger_at_bot', True)
        self.允许的群组 = 清理列表(过滤配置.get('allowed_groups', []))
        self.允许的用户 = 清理列表(过滤配置.get('allowed_users', []))
        self.转发所有消息 = 过滤配置.get('forward_all_messages', False)
        self.最大消息长度 = 过滤配置.get('max_message_length', 2000)
        self.引用唤醒 = 过滤配置.get('reply_to_hermes_trigger', True)

        # 冲突处理方式
        self.同时唤醒处理方式 = 冲突配置.get('llm_hermes_conflict_mode', 'hermes_only')

        # /approve 授权配置
        self.approve_启用 = approve配置.get('approve_enabled', True)
        self.approve_允许用户 = 清理列表(approve配置.get('approve_users', []))

        # /deny 授权配置
        self.deny_启用 = approve配置.get('deny_enabled', True)
        self.deny_允许用户 = 清理列表(approve配置.get('deny_users', []))

        # 指令执行配置
        self.指令白名单 = 清理列表(指令配置.get('command_whitelist', []))
        self.指令黑名单 = 指令配置.get('command_blacklist', ['重启', '关机', '更新'])

        # 表情回应配置
        emoji配置 = config.get('emoji_like', {})
        self.emoji_like_启用 = emoji配置.get('enabled', False)
        self.emoji_like_id列表 = emoji配置.get('emoji_ids', [12, 66, 76, 108, 122, 124, 144, 147, 175, 180, 192, 201, 282, 297])

        # ========== 内部状态 ==========
        self.http_运行器 = None
        self.http_站点 = None
        self.会话 = None
        self.处理器缓存: Dict[str, Dict] = {}
        self.别名到指令: Dict[str, str] = {}
        self._所有指令集合: set = set()  # 所有指令名+别名的集合

        # WebSocket 相关
        self.ws_连接 = None
        self._ws_任务 = None
        self.ws_已连接 = False
        self.重连延迟 = 1.0
        self.最大重连延迟 = 60.0

        # 存储每个群的最新 event 对象
        self.群组事件: Dict[str, AiocqhttpMessageEvent] = {}
        # 存储每个用户的私聊最新 event 对象
        self.私聊事件: Dict[str, AiocqhttpMessageEvent] = {}
        # 记录 Hermes 发送的消息 ID（用于引用唤醒）
        self.hermes_消息id集合: set = set()
        self.hermes_消息id_最大数量 = 1000

        self.统计数据 = {
            'messages_forwarded': 0,
            'commands_executed': 0,
            'errors': 0,
            'ws_reconnects': 0,
            'start_time': time.time()
        }
        self.已转发键 = "[Hermes适配器] 已转发"

        logger.info("[Hermes适配器] 插件已加载 (WebSocket 版本)")
        logger.info("[Hermes适配器] ═══ 连接配置 ═══")
        logger.info(f"[Hermes适配器]   Hermes WebSocket: {self.hermes_ws_链接}")
        logger.info(f"[Hermes适配器]   OneBot API: {self.onebot_api_地址}")
        logger.info(f"[Hermes适配器]   OneBot API 令牌: {self.onebot_api_token}")
        logger.info("[Hermes适配器] ═══ HTTP 服务器 ═══")
        logger.info(f"[Hermes适配器]   启用: {'是' if self.启用_http_服务器 else '否'}")
        logger.info(f"[Hermes适配器]   地址: {self.http_服务器_地址}")
        logger.info(f"[Hermes适配器]   令牌: {'已设置' if self.http_服务器_令牌 else '无'}")
        logger.info("[Hermes适配器] ═══ 消息过滤 ═══")
        logger.info(f"[Hermes适配器]   触发关键词: {self.触发关键词}")
        logger.info(f"[Hermes适配器]   @机器人触发: {'是' if self.触发艾特机器人 else '否'}")
        logger.info(f"[Hermes适配器]   允许的群组: {self.允许的群组 or '全部'}")
        logger.info(f"[Hermes适配器]   允许的用户: {self.允许的用户 or '全部'}")
        logger.info(f"[Hermes适配器]   转发所有消息: {'是' if self.转发所有消息 else '否'}")
        logger.info(f"[Hermes适配器]   最大消息长度: {self.最大消息长度}")
        logger.info(f"[Hermes适配器]   引用Hermes消息唤醒: {'是' if self.引用唤醒 else '否'}")
        logger.info("[Hermes适配器] ═══ 冲突处理 ═══")
        logger.info(f"[Hermes适配器]   模式: {self.同时唤醒处理方式}")
        logger.info("[Hermes适配器] ═══ 授权命令 ═══")
        logger.info(f"[Hermes适配器]   /approve: {'启用' if self.approve_启用 else '禁用'} (用户: {self.approve_允许用户 or '全部'})")
        logger.info(f"[Hermes适配器]   /deny: {'启用' if self.deny_启用 else '禁用'} (用户: {self.deny_允许用户 or '全部'})")
        logger.info("[Hermes适配器] ═══ 指令过滤 ═══")
        logger.info(f"[Hermes适配器]   白名单: {self.指令白名单 or '无限制'}")
        logger.info(f"[Hermes适配器]   黑名单: {self.指令黑名单}")
        logger.info("[Hermes适配器] ═══ 表情回应 ═══")
        logger.info(f"[Hermes适配器]   启用: {'是' if self.emoji_like_启用 else '否'}")
        logger.info(f"[Hermes适配器]   表情ID: {self.emoji_like_id列表}")
        logger.debug("[Hermes适配器]   最后修改：2026-4-29 7:57")

    # ========== 缓存管理 ==========

    def rebuild_cache(self):
        """重建指令处理器缓存"""
        self.处理器缓存, self.别名到指令 = build_command_cache(self.context)
        self._所有指令集合 = build_all_commands_set(self.处理器缓存, self.别名到指令)

    def 记录hermes消息id(self, message_id: str):
        """记录 Hermes 发送的消息 ID"""
        if not message_id:
            return
        self.hermes_消息id集合.add(str(message_id))
        # 超出上限时清理最早的（简单实现：直接清一半）
        if len(self.hermes_消息id集合) > self.hermes_消息id_最大数量:
            保留数量 = self.hermes_消息id_最大数量 // 2
            self.hermes_消息id集合 = set(list(self.hermes_消息id集合)[-保留数量:])
            # logger.debug(f"[Hermes适配器] 清理 hermes 消息 ID 缓存，保留 {保留数量} 条")

    async def emoji_like(self, message_id: int):
        """给消息贴表情回应（异步，不阻塞）"""
        if not self.emoji_like_启用 or not message_id:
            return
        try:
            import random
            from .onebot_api import set_msg_emoji_like
            emoji_id = random.choice(self.emoji_like_id列表)
            asyncio.create_task(set_msg_emoji_like(
                self.会话, self.onebot_api_地址, message_id, emoji_id, self.onebot_api_token
            ))
            # logger.debug(f"[Hermes适配器] 已发起表情回应: message_id={message_id}, emoji_id={emoji_id}")
        except Exception as e:
            logger.error(f"[Hermes适配器] 表情回应发起失败: {e}")

    # ========== 生命周期 ==========

    async def initialize(self):
        """异步初始化"""
        import os
        import glob
        
        self.会话 = aiohttp.ClientSession()
        self.rebuild_cache()

        # 打印插件目录下所有 py/pyc 文件的最后修改日期
        插件目录 = os.path.dirname(__file__)
        py文件 = glob.glob(os.path.join(插件目录, "*.py"))
        pyc文件 = glob.glob(os.path.join(插件目录, "__pycache__", "*.pyc"))
        所有文件 = py文件 + pyc文件

        # 计算最长文件名长度用于对齐
        最长文件名 = max(len(os.path.basename(f)) for f in 所有文件) if 所有文件 else 0

        logger.debug("[Hermes适配器] ═══ 文件修改时间 ═══")
        for 文件路径 in sorted(所有文件):
            文件名 = os.path.basename(文件路径)
            修改时间 = os.path.getmtime(文件路径)
            修改时间_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(修改时间))
            logger.debug(f"[Hermes适配器]   {文件名:<{最长文件名}}  {修改时间_str}")
        
        当前时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"[Hermes适配器]   {'当前时间':<{最长文件名}}  {当前时间}")
        logger.debug("[Hermes适配器] ═══════════════════════")

        if self.启用_http_服务器:
            await start_http_server(self)

        self._ws_任务 = asyncio.create_task(ws_loop(self))
        logger.info("[Hermes适配器] 初始化完成")

    async def terminate(self):
        """插件终止时清理资源"""
        if self._ws_任务:
            self._ws_任务.cancel()
            try:
                await self._ws_任务
            except asyncio.CancelledError:
                pass

        if self.ws_连接:
            await self.ws_连接.close()

        await stop_http_server(self)

        if self.会话:
            await self.会话.close()

        logger.info("[Hermes适配器] 插件已停止")

    # ========== 消息监听和转发 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    async def on_message(self, event: AiocqhttpMessageEvent):
        """监听所有消息（群聊+私聊），存储 event 并转发给 Hermes"""
        消息链 = event.get_messages()
        if not 消息链:
            return
        消息内容 = event.get_message_str()
        群号 = event.get_group_id()
        用户id = event.get_sender_id()
        用户名 = event.get_sender_name()
        if 群号:
            self.群组事件[群号] = event
        else:
            self.私聊事件[用户id] = event

        # 判断是否为框架指令：空格分割后第一个词在指令集合中则跳过
        if 消息内容:
            第一个词 = 消息内容.split()[0].lower() if 消息内容.split() else ''
            if 第一个词 and 第一个词 in self._所有指令集合:
                # logger.debug(f"[Hermes适配器] 跳过框架指令: {第一个词}")
                return

        # 判断是否引用了 Hermes 发送的消息
        引用hermes消息 = False
        if self.引用唤醒:
            if 消息链 and isinstance(消息链[0], Reply):
                引用的消息id = str(消息链[0].id)
                # logger.debug(f"[Hermes适配器] 引用消息ID={引用的消息id}, hermes消息ID集合={self.hermes_消息id集合}")
                if 引用的消息id in self.hermes_消息id集合:
                    引用hermes消息 = True
                    logger.info(f"[Hermes适配器] 检测到引用 Hermes 消息: {引用的消息id}，直接唤醒")

        if not should_forward(
            event, 消息内容,
            self.转发所有消息, self.允许的群组, self.允许的用户,
            self.触发关键词, self.触发艾特机器人,
            self.approve_启用, self.approve_允许用户,
            self.deny_启用, self.deny_允许用户,
            引用hermes消息
        ):
            return

        if not self._是否唤醒处理(event):
            return

        onebot事件体 = await build_onebot_event(
            event, 消息内容, self.最大消息长度, self.已转发键
        )

        await ws_send(self, onebot事件体)
        event.set_extra(self.已转发键, True)
        self.统计数据['messages_forwarded'] += 1
        来源 = "群聊" if 群号 else "私聊"
        logger.info(f"[Hermes适配器] 已转发[{用户名}] 的{来源}消息到 Hermes：{消息内容[:50]}")

    def _是否唤醒处理(self, event: AiocqhttpMessageEvent) -> bool:
        """判断 LLM 和 Hermes 同时唤醒时的处理方式"""
        if self.同时唤醒处理方式 == 'hermes_only':
            logger.info("[Hermes适配器] 终止事件，使用hermes")
            event.stop_event()
            return True
        elif self.同时唤醒处理方式 == 'both':
            if event.is_at_or_wake_command:
                logger.info("[Hermes适配器] 已同时唤醒")
            return True
        elif self.同时唤醒处理方式 == 'llm_only':
            if event.is_at_or_wake_command:
                logger.info("[Hermes适配器] llm已唤醒，不使用hermes")
                return False
            logger.info("[Hermes适配器] llm未唤醒，使用hermes")
            event.stop_event()
            return True
        return False

    # ========== 用户指令 ==========

    @filter.command_group("hermes")
    async def hermes_cmd(self, event: AiocqhttpMessageEvent):
        pass

    @hermes_cmd.command("status")
    async def cmd_status(self, event: AiocqhttpMessageEvent):
        """查看 Hermes 适配器状态"""
        运行耗时 = time.time() - self.统计数据['start_time']
        小时数 = int(运行耗时 // 3600)
        分钟数 = int((运行耗时 % 3600) // 60)
        ws状态 = "已连接" if self.ws_已连接 else "未连接"

        输出行 = [
            'Hermes 适配器状态 (WebSocket 版本)',
            f'运行时间: {小时数}小时{分钟数}分钟',
            f'WebSocket: {ws状态}',
            f'已缓存指令: {len(self.处理器缓存)}个',
            f'已缓存群: {len(self.群组事件)}个',
            f'已缓存私聊: {len(self.私聊事件)}个',
            f'转发消息: {self.统计数据["messages_forwarded"]}条',
            f'执行指令: {self.统计数据["commands_executed"]}次',
            f'错误次数: {self.统计数据["errors"]}次',
            f'重连次数: {self.统计数据["ws_reconnects"]}次',
            '',
            f'Hermes WebSocket: {self.hermes_ws_链接}',
            f'HTTP 服务器: http://{self.http_服务器_地址}',
            f'已缓存群列表: {", ".join(self.群组事件.keys()) or "无"}',
        ]
        yield event.plain_result('\n'.join(输出行))

    @hermes_cmd.command("test")
    async def cmd_test(self, event: AiocqhttpMessageEvent):
        """测试与 Hermes 的连接"""
        if self.ws_已连接:
            yield event.plain_result('WebSocket 已连接到 Hermes')
        else:
            yield event.plain_result('WebSocket 未连接')

    # ========== LLM 工具 ==========

    @filter.llm_tool("hermes_agent")
    async def hermes_agent(self, event: AiocqhttpMessageEvent, task: str, command: str = "", args: str = "") -> str:
        """
        调用 Hermes Agent 执行任务或命令。Hermes 是一个强大的 AI Agent，可以执行各种复杂任务。
        当用户需要执行复杂任务、查询信息、处理数据、调用其他插件功能时，可以使用此工具。

        Args:
            task(string): 任务描述，详细说明需要完成什么任务
            command(string): 具体要执行的 AstrBot 指令（可选，如 "点歌"、"群分析" 等）
            args(string): 指令参数（可选，如歌曲名、群号等）
        """
        try:
            group_id = event.get_group_id()

            if command:
                return await self._llm_execute_command(event, command, args, group_id)
            else:
                return await self._llm_forward_task(event, task)

        except Exception as e:
            logger.error(f"[Hermes适配器] LLM工具执行失败: {e}", exc_info=True)
            return f"执行失败: {str(e)}"

    async def _llm_execute_command(self, event: AiocqhttpMessageEvent, command: str, args: str, group_id: str) -> str:
        """LLM 工具：执行具体指令"""
        logger.info(f"[Hermes适配器] LLM工具执行指令: {command} {args}")

        可执行, 原因 = check_command_allowed(command, self.指令白名单, self.指令黑名单)
        if not 可执行:
            return f"指令执行被拒绝: {原因}"

        if not self.处理器缓存:
            self.rebuild_cache()

        处理器信息 = resolve_command(command, self.别名到指令, self.处理器缓存)
        if not 处理器信息:
            可用指令 = list(self.处理器缓存.keys())[:20]
            return f"未找到指令: {command}。可用指令: {', '.join(可用指令)}"

        执行结果 = await execute_command(
            self, 处理器信息, args,
            event.get_sender_id(), event.get_sender_name(), group_id
        )

        if 执行结果.get('success'):
            结果部分 = []
            if 执行结果.get('texts'):
                结果部分.append("执行结果:\n" + "\n".join(执行结果['texts']))
            if 执行结果.get('images'):
                结果部分.append(f"生成了 {len(执行结果['images'])} 张图片")
            return "\n".join(结果部分) if 结果部分 else "指令执行成功"
        else:
            return f"指令执行失败: {执行结果.get('error', '未知错误')}"

    async def _llm_forward_task(self, event: AiocqhttpMessageEvent, task: str) -> str:
        """LLM 工具：转发任务给 Hermes"""
        logger.info(f"[Hermes适配器] LLM工具执行任务: {task}")

        if not self.ws_已连接:
            return "Hermes Agent 未连接，请稍后再试"

        onebot事件体 = await build_onebot_event(
            event, event.get_message_str(), self.最大消息长度, self.已转发键
        )
        await ws_send(self, onebot事件体)
        event.set_extra(self.已转发键, True)
        self.统计数据['messages_forwarded'] += 1

        return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"

    @filter.llm_tool("hermes_status")
    async def hermes_status(self, _) -> str:
        """
        查询 Hermes Agent 和适配器的运行状态。

        Returns:
            str: 状态信息，包括连接状态、运行时间、统计信息等
        """
        运行耗时 = time.time() - self.统计数据['start_time']
        小时数 = int(运行耗时 // 3600)
        分钟数 = int((运行耗时 % 3600) // 60)
        ws状态 = "已连接" if self.ws_已连接 else "未连接"

        return "\n".join([
            "Hermes 适配器状态:",
            f"- WebSocket 连接: {ws状态}",
            f"- 运行时间: {小时数}小时{分钟数}分钟",
            f"- 已缓存指令: {len(self.处理器缓存)}个",
            f"- 已缓存群: {len(self.群组事件)}个",
            f"- 已缓存私聊: {len(self.私聊事件)}个",
            f"- 已转发消息: {self.统计数据['messages_forwarded']}条",
            f"- 已执行指令: {self.统计数据['commands_executed']}次",
            f"- 错误次数: {self.统计数据['errors']}次"
        ])

    @filter.llm_tool("hermes_list_commands")
    async def hermes_list_commands(self, _: AiocqhttpMessageEvent, category: str = "") -> str:
        """
        列出所有可通过 Hermes 执行的 AstrBot 指令。

        Args:
            category (str): 指令分类过滤（可选），如 "音乐"、"宠物"、"好感度" 等

        Returns:
            str: 指令列表，按分类组织
        """
        if not self.处理器缓存:
            self.rebuild_cache()

        分类字典 = categorize_commands(self.处理器缓存, 分类过滤=category)

        输出行 = []
        for 分类, items in sorted(分类字典.items()):
            输出行.append(f"\n【{分类}】")
            for 指令 in items[:10]:
                管理员标记 = " [管理员]" if 指令['is_admin'] else ""
                输出行.append(f"  - {指令['usage']}: {指令['description']}{管理员标记}")

        if not 输出行:
            return f"没有找到分类为 '{category}' 的指令" if category else "没有找到可用指令"

        return f"可用指令列表 (共{len(self.处理器缓存)}个):" + "\n".join(输出行)
