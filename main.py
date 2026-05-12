"""
Hermes Agent 适配器插件 - WebSocket 版本

实现 AstrBot 与 Hermes Agent 的双向通信：
- AstrBot → Hermes: 通过 WebSocket 连接到 Hermes 反向 WS 服务器
- Hermes → AstrBot: 接收 Hermes 指令请求，通过 HTTP API 执行

模块结构:
- onebot_client.py   : OneBotClient - OneBot HTTP API 客户端
- emoji_manager.py   : EmojiManager - 表情回应与消息 ID 追踪
- message_handler.py : 消息管理器 - 消息过滤与事件体构造
- command_manager.py : CommandManager - 指令缓存/执行/LLM 工具
- http_server.py     : HttpServer - HTTP API 服务器
- ws_client.py       : WebSocketClient - WebSocket 连接管理
"""
import asyncio
import time
import os
import glob
import json
import aiohttp
from typing import Dict
from astrbot.api.event import filter
from astrbot.api.all import Star, Context, AstrBotConfig, logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from .onebot_client import OneBotClient
from .emoji_manager import EmojiManager
from .message_handler import 消息管理器
from .command_manager import CommandManager
from .http_server import HttpServer
from .ws_client import WebSocketClient


class Hermes适配器(Star):
    """Hermes Agent 适配器 - WebSocket 版本"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # ========== 解析配置 ==========
        self._解析配置(config)

        # ========== 初始化组件 ==========
        self.会话 = None
        self.onebot_client: OneBotClient = None
        self.emoji_manager: EmojiManager = EmojiManager(config)
        self.消息管理器 = 消息管理器(config, self.emoji_manager)
        self.cmd_manager = CommandManager(self)
        self.http_server = HttpServer(self)
        self.ws_client: WebSocketClient = None

        # ========== 运行时状态 ==========
        self.群组事件: Dict[str, AiocqhttpMessageEvent] = {}
        self.私聊事件: Dict[str, AiocqhttpMessageEvent] = {}
        self.统计数据 = {
            'messages_forwarded': 0,
            'commands_executed': 0,
            'errors': 0,
            'ws_reconnects': 0,
            'start_time': time.time()
        }

    # ========== 配置解析 ==========

    def _解析配置(self, config):
        """解析所有配置项"""
        def 清理列表(lst):
            return [i.strip() for i in lst if i.strip()]

        # 连接配置
        连接配置: dict = config['连接配置']
        self.hermes_ws_url = 连接配置['hermes_ws_url']
        self.hermes_token = 连接配置['hermes_token']
        self.onebot_api_url = 连接配置['onebot_api_url']
        self.onebot_api_token = 连接配置['onebot_api_token']

        # HTTP 配置
        http配置: dict = config['http配置']
        self.启用_http_服务器 = http配置['启用_http_服务器']
        self.http_服务器_地址 = http配置['http_服务器_地址']
        self.http_服务器_token = http配置['http_服务器_token']

        try:
            parts = str(self.http_服务器_地址).rsplit(':', 1)
            self.http_服务器_主机 = parts[0]
            self.http_服务器_端口 = int(parts[1])
        except Exception as e:
            self.http_服务器_主机 = '127.0.0.1'
            self.http_服务器_端口 = int(self.http_服务器_地址)
            logger.error(f"解析 HTTP 服务器地址失败，地址原文：{self.http_服务器_地址}\n{e}", exc_info=True)
            logger.warning(f"使用默认值：{self.http_服务器_主机}:{self.http_服务器_端口}")

        # 安全配置
        安全配置: dict = config['安全配置']
        self.敏感字符列表 = 清理列表(安全配置['敏感字符列表'])
        config['安全配置']['敏感字符列表'] = self.敏感字符列表
        self.替换目标 = 安全配置['替换目标']

        # 自动从 AstrBot 配置读取 API 密钥
        self._加载api密钥(config)

        # 指令配置
        指令配置: dict = config['指令配置']
        self.指令白名单 = 清理列表(指令配置['指令白名单'])
        self.指令黑名单 = 指令配置['指令黑名单']

    def _加载api密钥(self, config):
        """从 AstrBot cmd_config.json 自动加载 API 密钥到敏感字符列表"""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.dirname(os.path.dirname(script_dir))
            cmd_config_path = os.path.join(data_dir, 'cmd_config.json')
            with open(cmd_config_path, 'r', encoding='utf-8-sig') as f:
                cmd_config = json.load(f)
            for source in cmd_config.get('provider_sources', []):
                keys = source.get('key', [])
                if isinstance(keys, str):
                    keys = [keys]
                self.敏感字符列表.extend(keys)
            self.敏感字符列表 = list(dict.fromkeys(self.敏感字符列表))
            config['安全配置']['敏感字符列表'] = self.敏感字符列表
            logger.info(f"[Hermes适配器] 已从配置文件自动加载 {len(self.敏感字符列表)} 个密钥字符")
        except Exception as e:
            logger.warning(f"[Hermes适配器] 自动读取 AstrBot 密钥失败: {e}")

    # ========== 生命周期 ==========

    async def initialize(self):
        """异步初始化"""
        self.会话 = aiohttp.ClientSession()
        self.onebot_client = OneBotClient(self.会话, self.onebot_api_url, self.onebot_api_token)

        self.cmd_manager.rebuild_cache()
        self._打印文件修改时间()

        if self.启用_http_服务器:
            await self.http_server.start(self.http_服务器_主机, self.http_服务器_端口)

        self.ws_client = WebSocketClient(
            self.hermes_ws_url, self.hermes_token,
            self.onebot_client, self
        )
        await self.ws_client.start()

        logger.info("[Hermes适配器] 初始化完成")

    async def terminate(self):
        """插件终止时清理资源"""
        if self.ws_client:
            await self.ws_client.stop()
        await self.http_server.stop()
        if self.会话:
            await self.会话.close()
        logger.info("[Hermes适配器] 插件已停止")

    # ========== 消息监听 ==========

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    async def on_message(self, event: AiocqhttpMessageEvent):
        """监听所有消息（群聊+私聊），存储 event 并转发给 Hermes"""
        消息链 = event.get_messages()
        if not 消息链:
            return

        if not isinstance(event, AiocqhttpMessageEvent):
            return

        消息内容 = event.get_message_str()
        群号 = event.get_group_id()
        用户id = event.get_sender_id()
        用户名 = event.get_sender_name()

        # 缓存 event
        if 群号:
            self.群组事件[群号] = event
        else:
            self.私聊事件[用户id] = event

        # 跳过框架指令
        if self.cmd_manager.是框架指令(消息内容):
            return

        # 判断是否转发
        if not self.消息管理器.是否转发(event):
            return

        # 构造事件体并发送
        onebot事件体 = await self.消息管理器.构造onebot事件体(event)
        await self.ws_client.send(onebot事件体)
        event.set_extra(self.消息管理器.已转发键, True)
        self.统计数据['messages_forwarded'] += 1

        # 转发成功后贴表情
        if self.emoji_manager.转发时贴表情:
            await self.emoji_manager.贴表情(self.onebot_client, event.message_obj.message_id)

        来源 = "群聊" if 群号 else "私聊"
        logger.info(f"[Hermes适配器] 已转发[{用户名}] 的{来源}消息到 Hermes：{消息内容[:50]}")

    # ========== 用户指令 ==========

    @filter.command_group("hermes")
    async def hermes_cmd(self, event: AiocqhttpMessageEvent):
        pass

    @hermes_cmd.command("status", alias={"状态"})
    async def cmd_status(self, event: AiocqhttpMessageEvent):
        """查看 Hermes 适配器状态"""
        运行耗时 = time.time() - self.统计数据['start_time']
        小时数 = int(运行耗时 // 3600)
        分钟数 = int((运行耗时 % 3600) // 60)
        ws状态 = "已连接" if self.ws_client.已连接 else "未连接"

        输出行 = [
            'Hermes 适配器状态 (WebSocket 版本)',
            f'运行时间: {小时数}小时{分钟数}分钟',
            f'WebSocket: {ws状态}',
            f'已缓存指令: {len(self.cmd_manager.处理器缓存)}个',
            f'已缓存群: {len(self.群组事件)}个',
            f'已缓存私聊: {len(self.私聊事件)}个',
            f'转发消息: {self.统计数据["messages_forwarded"]}条',
            f'执行指令: {self.统计数据["commands_executed"]}次',
            f'错误次数: {self.统计数据["errors"]}次',
            f'重连次数: {self.统计数据["ws_reconnects"]}次',
            '',
            f'Hermes WebSocket: {self.hermes_ws_url}',
            f'HTTP 服务器: http://{self.http_服务器_地址}',
            f'已缓存群列表: {", ".join(self.群组事件.keys()) or "无"}',
        ]
        yield event.plain_result('\n'.join(输出行))

    @hermes_cmd.command("test")
    async def cmd_test(self, event: AiocqhttpMessageEvent):
        """测试与 Hermes 的连接"""
        if self.ws_client.已连接:
            yield event.plain_result('WebSocket 已连接到 Hermes')
        else:
            yield event.plain_result('WebSocket 未连接')

    # ========== LLM 工具 ==========

    @filter.llm_tool("hermes_task")
    async def hermes_task(self, event: AiocqhttpMessageEvent, task: str) -> str:
        """
        将复杂任务转发给 Hermes Agent 自主执行。Hermes 是一个强大的 AI Agent，可以处理复杂任务。
        当用户需要执行无法通过现有指令完成的复杂任务时（如信息查询、数据分析、复杂操作等），使用此工具。
        Hermes 会自行决策并回复结果。

        Args:
            task(string): 任务描述，详细说明需要 Hermes 完成的任务内容
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "当前平台不支持Hermes"
        try:
            return await self._llm_forward_task(event, task)
        except Exception as e:
            logger.error(f"[Hermes适配器] LLM工具转发任务失败: {e}", exc_info=True)
            return f"转发任务失败: {str(e)}"

    @filter.llm_tool("hermes_command")
    async def hermes_command(self, event: AiocqhttpMessageEvent, command: str, args: str = "") -> str:
        """
        调用 Hermes 适配器执行指定的 AstrBot 指令。所有 AstrBot 插件指令都可以通过此工具执行。
        当用户需要执行具体的机器人指令时（如点歌、查询、分析等），使用此工具。

        Args:
            command(string): 要执行的 AstrBot 指令名称（如 "点歌"、"群分析"、"状态" 等）
            args(string): 指令参数（可选，如歌曲名、群号等）
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "当前平台不支持Hermes"
        try:
            return await self._llm_execute_command(event, command, args)
        except Exception as e:
            logger.error(f"[Hermes适配器] LLM工具执行指令失败: {e}", exc_info=True)
            return f"执行指令失败: {str(e)}"

    async def _llm_execute_command(self, event: AiocqhttpMessageEvent, command: str, args: str) -> str:
        """LLM 工具：执行具体指令"""
        logger.info(f"[Hermes适配器] LLM工具执行指令: {command} {args}")

        allowed, reason = self.cmd_manager.check_allowed(command)
        if not allowed:
            return f"指令执行被拒绝: {reason}"

        if not self.cmd_manager.处理器缓存:
            self.cmd_manager.rebuild_cache()

        handler_info = self.cmd_manager.resolve_command(command)
        if not handler_info:
            available = list(self.cmd_manager.处理器缓存.keys())[:20]
            return f"未找到指令: {command}。可用指令: {', '.join(available)}"

        result = await self.cmd_manager.execute_command(
            command, args,
            event.get_sender_id(), event.get_sender_name(),
            event.get_group_id()
        )

        if result.get('success'):
            parts = []
            if result.get('texts'):
                parts.append("执行结果:\n" + "\n".join(result['texts']))
            if result.get('images'):
                parts.append(f"生成了 {len(result['images'])} 张图片")
            return "\n".join(parts) if parts else "指令执行成功"
        else:
            return f"指令执行失败: {result.get('error', '未知错误')}"

    async def _llm_forward_task(self, event: AiocqhttpMessageEvent, task: str) -> str:
        """LLM 工具：转发任务给 Hermes"""
        logger.info(f"[Hermes适配器] LLM工具执行任务: {task}")

        if not self.ws_client.已连接:
            return "Hermes Agent 未连接，请稍后再试"

        onebot事件体 = await self.消息管理器.构造onebot事件体(event)
        await self.ws_client.send(onebot事件体)
        event.set_extra(self.消息管理器.已转发键, True)
        self.统计数据['messages_forwarded'] += 1

        return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"

    @filter.llm_tool("hermes_status")
    async def hermes_status(self, _) -> str:
        """
        查询 Hermes Agent 和适配器的运行状态。

        Returns:
            str: 状态信息，包括连接状态、运行时间、统计信息等
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "当前平台不支持Hermes"
        运行耗时 = time.time() - self.统计数据['start_time']
        小时数 = int(运行耗时 // 3600)
        分钟数 = int((运行耗时 % 3600) // 60)
        ws状态 = "已连接" if self.ws_client.已连接 else "未连接"

        return "\n".join([
            "Hermes 适配器状态:",
            f"- WebSocket 连接: {ws状态}",
            f"- 运行时间: {小时数}小时{分钟数}分钟",
            f"- 已缓存指令: {len(self.cmd_manager.处理器缓存)}个",
            f"- 已缓存群: {len(self.群组事件)}个",
            f"- 已缓存私聊: {len(self.私聊事件)}个",
            f"- 已转发消息: {self.统计数据['messages_forwarded']}条",
            f"- 已执行指令: {self.统计数据['commands_executed']}次",
            f"- 错误次数: {self.统计数据['errors']}次"
        ])

    @filter.llm_tool("hermes_list_commands")
    async def hermes_list_commands(self, _, category: str = "") -> str:
        """
        列出所有可通过 Hermes 执行的 AstrBot 指令。

        Args:
            category (str): 指令分类过滤（可选），如 "音乐"、"宠物"、"好感度" 等

        Returns:
            str: 指令列表，按分类组织
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "当前平台不支持Hermes"

        if not self.cmd_manager.处理器缓存:
            self.cmd_manager.rebuild_cache()

        categorized = self.cmd_manager.categorize_commands(category_filter=category)

        输出行 = []
        for cat, items in sorted(categorized.items()):
            输出行.append(f"\n【{cat}】")
            for cmd in items[:10]:
                admin_tag = " [管理员]" if cmd['is_admin'] else ""
                输出行.append(f"  - {cmd['usage']}: {cmd['description']}{admin_tag}")

        if not 输出行:
            return f"没有找到分类为 '{category}' 的指令" if category else "没有找到可用指令"

        return f"可用指令列表 (共{len(self.cmd_manager.处理器缓存)}个):" + "\n".join(输出行)

    # ========== 工具方法 ==========

    def _打印文件修改时间(self):
        """打印插件目录下所有 py/pyc 文件的最后修改日期"""
        插件目录 = os.path.dirname(__file__)
        py文件 = glob.glob(os.path.join(插件目录, "*.py"))
        pyc文件 = glob.glob(os.path.join(插件目录, "__pycache__", "*.pyc"))
        所有文件 = py文件 + pyc文件

        if not 所有文件:
            return

        最长文件名 = max(len(os.path.basename(f)) for f in 所有文件)
        logger.debug("[Hermes适配器] ═══ 文件修改时间 ═══")
        for f in sorted(所有文件):
            文件名 = os.path.basename(f)
            修改时间 = os.path.getmtime(f)
            修改时间_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(修改时间))
            logger.debug(f"[Hermes适配器]   {文件名:<{最长文件名}}  {修改时间_str}")
        当前时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"[Hermes适配器]   {'当前时间':<{最长文件名}}  {当前时间}")
        logger.debug("[Hermes适配器] ═══════════════════════")
