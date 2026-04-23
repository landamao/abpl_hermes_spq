"""
Hermes Agent 适配器插件 - WebSocket 版本

实现 AstrBot 与 Hermes Agent 的双向通信：
- AstrBot → Hermes: 通过 WebSocket 连接到 Hermes 反向 WS 服务器
- Hermes → AstrBot: 接收 Hermes 指令请求，通过 HTTP API 执行
"""
import websockets, asyncio, json, time, copy, aiohttp
from typing import Dict, Any
from aiohttp import web
from astrbot.api.event import filter
from astrbot.api.all import (
    Star, Context, AstrBotConfig, logger,
    Plain, Image, At, Json,
    AstrBotMessage, MessageMember, MessageType, MessageChain
)

from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


class Hermes适配器(Star):
    """
    Hermes Agent 适配器 - WebSocket 版本
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        def 清理列表(列表):
            return [ i.strip() for i in 列表 if i.strip()]
        # ========== 配置项 ==========
        # WebSocket 连接到 Hermes
        self.hermes_ws_链接 = config.get('hermes_ws_url', 'ws://127.0.0.1:6701')
        self.hermes_访问令牌 = config.get('hermes_access_token', '')

        # OneBot API 地址（用于转发消息到 NapCat）
        self.onebot_api_地址 = config.get('onebot_api_url', 'http://127.0.0.1:5700')

        # HTTP API 服务器（Hermes 调用）
        self.启用_http_服务器 = config.get('enable_http_server', True)
        self.http_服务器_端口 = config.get('http_server_port', 8567)
        self.http_服务器_令牌 = config.get('http_server_token', '')

        # 消息过滤配置
        self.触发关键词 = config.get('trigger_keywords', ['纳西妲', 'hermes', 'Hermes'])
        self.触发艾特机器人 = config.get('trigger_at_bot', True)
        self.允许的群组 = 清理列表(config.get('allowed_groups', []))
        self.允许的用户 = 清理列表(config.get('allowed_users', []))
        self.转发所有消息 = config.get('forward_all_messages', False)
        self.最大消息长度 = config.get('max_message_length', 2000)

        # /approve 和 /deny 授权配置
        self.approve_deny_启用 = config.get('approve_deny_enabled', True)
        self.approve_deny_允许用户 = 清理列表(config.get('approve_deny_users', []))

        # 指令执行配置
        self.指令白名单 = 清理列表(config.get('command_whitelist', []))
        self.指令黑名单 = config.get('command_blacklist', ['重启', '关机', '更新'])

        # ========== 内部状态 ==========
        self._http_运行器 = None
        self._http_站点 = None
        self._会话 = None
        self._处理器缓存: Dict[str, Dict] = {}
        self._别名到指令: Dict[str, str] = {}

        # WebSocket 相关
        self._ws_连接 = None
        self._ws_任务 = None
        self._ws_已连接 = False
        self._重连延迟 = 1.0
        self._最大重连延迟 = 60.0

        # 存储每个群的最新 event 对象
        self._群组事件: Dict[str, AiocqhttpMessageEvent] = {}

        self.统计数据 = {
            'messages_forwarded': 0,
            'commands_executed': 0,
            'errors': 0,
            'ws_reconnects': 0,
            'start_time': time.time()
        }
        self.已转发键 = "[HermesAdapter] 已转发"
        logger.info("[HermesAdapter] 插件已加载 (WebSocket 版本)")
        logger.info(f"[HermesAdapter]   - Hermes WebSocket: {self.hermes_ws_链接}")
        logger.info(f"[HermesAdapter]   - HTTP 服务器: {'启用' if self.启用_http_服务器 else '禁用'} (端口: {self.http_服务器_端口})")
        logger.info(f"[HermesAdapter]   - 触发关键词: {self.触发关键词}")
        logger.info( "[HermesAdapter]   - 最后修改：4-23_16:44")

    def _构建处理器缓存(self):
        """构建指令处理器缓存"""
        self._处理器缓存.clear()
        self._别名到指令.clear()

        try:
            # noinspection PyUnresolvedReferences
            所有插件 = self.context.get_all_stars()
            所有插件 = [插件实例 for 插件实例 in 所有插件 if 插件实例.activated]
        except Exception as 异常:
            logger.error(f"[HermesAdapter] 获取插件列表失败: {异常}")
            return

        if not 所有插件:
            return

        跳过插件 = {"astrbot", "hermes_adapter"}

        模块映射插件 = {}
        for 插件实例 in 所有插件:
            插件名称 = getattr(插件实例, "name", "未知插件")
            模块路径 = getattr(插件实例, "module_path", None)
            if 插件名称 in 跳过插件 or not 模块路径:
                continue
            模块映射插件[模块路径] = (插件实例, 插件名称)

        for 处理器 in star_handlers_registry:
            if not isinstance(处理器, StarHandlerMetadata):
                continue

            插件信息 = 模块映射插件.get(处理器.handler_module_path)
            if not 插件信息:
                continue

            插件实例, 插件名称 = 插件信息

            指令名称 = None
            别名集合 = []
            指令描述 = 处理器.desc or "无描述"
            是否管理员指令 = False

            for 过滤器 in 处理器.event_filters:
                if isinstance(过滤器, CommandFilter):
                    指令名称 = 过滤器.command_name
                    if hasattr(过滤器, 'alias') and 过滤器.alias:
                        if isinstance(过滤器.alias, set):
                            别名集合 = list(过滤器.alias)
                        elif isinstance(过滤器.alias, list):
                            别名集合 = 过滤器.alias
                elif isinstance(过滤器, CommandGroupFilter):
                    指令名称 = 过滤器.group_name
                elif isinstance(过滤器, PermissionTypeFilter):
                    是否管理员指令 = True

            if 指令名称:
                if 指令名称.startswith("/"):
                    指令名称 = 指令名称[1:]

                处理器信息 = {
                    "command": 指令名称,
                    "description": 指令描述,
                    "plugin": 插件名称,
                    "aliases": 别名集合,
                    "is_admin": 是否管理员指令,
                    "handler": 处理器,
                    "module_path": 处理器.handler_module_path
                }

                self._处理器缓存[指令名称] = 处理器信息

                for 别名 in 别名集合:
                    if 别名.startswith("/"):
                        别名 = 别名[1:]
                    self._别名到指令[别名] = 指令名称

        logger.info(f"[HermesAdapter] 已缓存 {len(self._处理器缓存)} 个指令处理器")

    def _检查能否执行指令(self, 指令: str) -> tuple[bool, str]:
        """检查指令是否允许执行"""
        if 指令.startswith('/'):
            指令 = 指令[1:]

        if self.指令黑名单 and 指令 in self.指令黑名单:
            return False, f'指令 {指令} 在黑名单中'

        if self.指令白名单 and 指令 not in self.指令白名单:
            return False, f'指令 {指令} 不在白名单中'

        return True, '可以执行'

    async def _发送至onebot(self, 群号: int, 消息内容: str) -> dict:
        """直接通过 OneBot API 发送消息到群"""
        请求网址 = f"{self.onebot_api_地址}/send_group_msg"
        请求负载 = {
            "message_type": "group",
            "group_id": 群号,
            "message": 消息内容
        }

        try:
            async with self._会话.post(请求网址, json=请求负载) as 响应:
                结果数据 = await 响应.json()
                logger.info(f"[HermesAdapter] OneBot 发送结果: {结果数据}")
                return 结果数据
        except Exception as 异常:
            logger.error(f"[HermesAdapter] OneBot 发送失败: {异常}")
            return {"error": str(异常)}

    async def _发送cq码至onebot(self, 群号: int, 消息内容: list) -> dict:
        """通过 OneBot API 发送 CQ 码格式消息"""
        请求网址 = f"{self.onebot_api_地址}/send_group_msg"
        请求负载 = {
            "message_type": "group",
            "group_id": 群号,
            "message": 消息内容
        }

        try:
            async with self._会话.post(请求网址, json=请求负载) as 响应:
                结果数据 = await 响应.json()
                logger.info(f"[HermesAdapter] OneBot CQ 发送结果: {结果数据}")
                return 结果数据
        except Exception as 异常:
            logger.error(f"[HermesAdapter] OneBot CQ 发送失败: {异常}")
            return {"error": str(异常)}

    async def initialize(self):
        """异步初始化"""
        self._会话 = aiohttp.ClientSession()
        self._构建处理器缓存()

        # 启动 HTTP 服务器
        if self.启用_http_服务器:
            await self._启动http服务器()

        # 启动 WebSocket 连接
        self._ws_任务 = asyncio.create_task(self._ws_循环())

        logger.info("[HermesAdapter] 初始化完成")

    async def terminate(self):
        """插件终止时清理资源"""
        # 停止 WebSocket 连接
        if self._ws_任务:
            self._ws_任务.cancel()
            try:
                await self._ws_任务
            except asyncio.CancelledError:
                pass

        if self._ws_连接:
            await self._ws_连接.close()

        # 停止 HTTP 服务器
        await self._停止http服务器()

        if self._会话:
            await self._会话.close()

        logger.info("[HermesAdapter] 插件已停止")

    # ========== WebSocket 连接 ==========

    async def _ws_循环(self):
        """WebSocket 连接循环"""
        while True:
            try:
                await self._ws_发起连接()
            except asyncio.CancelledError:
                break
            except Exception as 异常:
                logger.error(f"[HermesAdapter] WebSocket 连接异常: {异常}")

            # 等待后重连
            if self._ws_已连接:
                self._ws_已连接 = False
                logger.info("[HermesAdapter] WebSocket 断开，准备重连...")

            self.统计数据['ws_reconnects'] += 1
            logger.info(f"[HermesAdapter] 等待 {self._重连延迟:.1f}s 后重连...")
            await asyncio.sleep(self._重连延迟)

            # 指数退避
            self._重连延迟 = min(
                self._重连延迟 * 2,
                self._最大重连延迟
            )

    async def _ws_发起连接(self):
        """连接到 Hermes WebSocket"""


        请求头 = {}
        if self.hermes_访问令牌:
            请求头['Authorization'] = f'Bearer {self.hermes_访问令牌}'

        logger.info(f"[HermesAdapter] 正在连接到 Hermes: {self.hermes_ws_链接}")

        async with websockets.connect(
            self.hermes_ws_链接,
            additional_headers=请求头,
            ping_interval=20,
            ping_timeout=60
        ) as ws客户端:
            self._ws_连接 = ws客户端
            self._ws_已连接 = True
            self._重连延迟 = 1.0  # 重置重连延迟

            logger.info("[HermesAdapter] ✅ WebSocket 已连接到 Hermes")

            # 发送连接确认
            await self._ws_发送连接确认()

            # 监听消息
            async for 消息文本 in ws客户端:
                try:
                    await self._ws_处理消息(消息文本)
                except Exception as 异常:
                    logger.error(f"[HermesAdapter] 处理 WebSocket 消息失败: {异常}", exc_info=True)

    async def _ws_发送连接确认(self):
        """发送连接确认消息"""
        连接消息 = {
            "type": "connect",
            "platform": "qq",
            "self_id": "astrbot",
            "data": {}
        }
        await self._ws_发送数据(连接消息)

    async def _ws_发送数据(self, 数据: dict):
        """发送 WebSocket 消息"""
        if self._ws_连接 and self._ws_已连接:
            try:
                await self._ws_连接.send(json.dumps(数据, ensure_ascii=False))
            except Exception as 异常:
                logger.error(f"[HermesAdapter] WebSocket 发送失败: {异常}")
                self._ws_已连接 = False

    async def _ws_处理消息(self, 原始消息: str):
        """处理从 Hermes 收到的 WebSocket 消息"""
        try:
            logger.debug(f"[HermesAdapter] 收到 WebSocket 消息raw: {原始消息}")
            数据 = json.loads(原始消息)
            logger.debug(f"[HermesAdapter] 收到 WebSocket json后: {原始消息}")
            消息类型 = 数据.get('type', '')

            logger.debug(f"[HermesAdapter] 收到 WebSocket 消息: {消息类型}")

            if 消息类型 == 'api_request':
                # Hermes 请求执行 API
                await self._处理api请求(数据)
            elif 消息类型 == 'send_message':
                # Hermes 请求发送消息
                await self._处理发送消息(数据)
            elif 消息类型 == 'ping':
                # 心跳
                await self._ws_发送数据({"type": "pong"})
            elif 'action' in 数据 and 'echo' in 数据:
                # OneBot API 调用格式（直接包含 action 和 echo）
                await self._处理api请求(数据)
            elif 'action' in 数据:
                # OneBot API 调用（无 echo）
                await self._处理api请求(数据)
            else:
                logger.debug(f"[HermesAdapter] 未知消息类型: {消息类型}")

        except json.JSONDecodeError:
            logger.error(f"[HermesAdapter] 无效的 JSON 消息: {原始消息[:100]}")
        except Exception as 异常:
            logger.error(f"[HermesAdapter] 处理消息失败: {异常}", exc_info=True)

    async def _处理api请求(self, 数据: dict):
        """处理 Hermes 的 OneBot API 请求"""
        动作 = 数据.get('action', '')
        参数 = 数据.get('params', {})
        回声字段 = 数据.get('echo', '')

        logger.info(f"[HermesAdapter] 收到 API 请求: {动作}, echo={回声字段}")

        try:
            if 动作 == 'send_group_msg':
                群号 = 参数.get('group_id')
                消息内容 = 参数.get('message', '')

                if isinstance(消息内容, list):
                    # CQ 码格式
                    api返回结果 = await self._发送cq码至onebot(群号, 消息内容)
                else:
                    # 文本格式
                    api返回结果 = await self._发送至onebot(群号, 消息内容)

                # 转换为 OneBot 响应格式
                if api返回结果 and 'retcode' in api返回结果:
                    结果数据 = api返回结果
                elif api返回结果 and 'status' not in api返回结果:
                    结果数据 = {"status": "ok", "retcode": 0, "data": api返回结果, "msg": ""}
                else:
                    结果数据 = api返回结果

            elif 动作 == 'send_private_msg':
                用户id = 参数.get('user_id')
                消息内容 = 参数.get('message', '')

                请求网址 = f"{self.onebot_api_地址}/send_private_msg"
                请求负载 = {
                    "message_type": "private",
                    "user_id": 用户id,
                    "message": 消息内容
                }

                async with self._会话.post(请求网址, json=请求负载) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'get_group_info':
                群号 = 参数.get('group_id')
                请求网址 = f"{self.onebot_api_地址}/get_group_info"

                async with self._会话.get(请求网址, params={"group_id": 群号}) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'get_msg':
                message_id = 参数.get('message_id')
                请求网址 = f"{self.onebot_api_地址}/get_msg"

                async with self._会话.get(请求网址, params={"message_id": message_id}) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'set_msg_emoji_like':
                message_id = 参数.get('message_id')
                表情id = 参数.get('emoji_id', 12)

                请求网址 = f"{self.onebot_api_地址}/set_msg_emoji_like"
                请求负载 = {
                    "message_id": message_id,
                    "emoji_id": 表情id,
                    "set": 参数.get('set', True)
                }

                async with self._会话.post(请求网址, json=请求负载) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'send_forward_msg':
                消息列表 = 参数.get('messages', [])
                请求网址 = f"{self.onebot_api_地址}/send_forward_msg"

                async with self._会话.post(请求网址, json={"messages": 消息列表}) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'send_group_forward_msg':
                群号 = 参数.get('group_id')
                消息列表 = 参数.get('messages', [])
                请求网址 = f"{self.onebot_api_地址}/send_group_forward_msg"

                async with self._会话.post(请求网址, json={"group_id": 群号, "messages": 消息列表}) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'get_group_list':
                请求网址 = f"{self.onebot_api_地址}/get_group_list"

                async with self._会话.get(请求网址) as 响应:
                    结果数据 = await 响应.json()

            elif 动作 == 'get_group_member_info':
                群号 = 参数.get('group_id')
                用户id = 参数.get('user_id')
                请求网址 = f"{self.onebot_api_地址}/get_group_member_info"

                async with self._会话.get(请求网址, params={"group_id": 群号, "user_id": 用户id}) as 响应:
                    结果数据 = await 响应.json()

            else:
                logger.warning(f"[HermesAdapter] 未支持的 API 操作: {动作}")
                结果数据 = {"status": "failed", "retcode": 100, "msg": f"未支持的操作: {动作}", "data": None}

        except Exception as 异常:
            logger.error(f"[HermesAdapter] API 调用失败: {动作} - {异常}", exc_info=True)
            结果数据 = {"status": "failed", "retcode": 100, "msg": str(异常), "data": None}

        # 发送 OneBot 格式的响应（必须包含 echo 字段）
        if 回声字段:
            响应字典 = {
                "status": 结果数据.get("status", "failed"),
                "retcode": 结果数据.get("retcode", 0),
                "data": 结果数据.get("data"),
                "msg": 结果数据.get("msg", ""),
                "echo": 回声字段
            }
            await self._ws_发送数据(响应字典)
            logger.debug(f"[HermesAdapter] 已发送 API 响应: {动作}, echo={回声字段}")

    async def _处理发送消息(self, 数据: dict):
        """处理 Hermes 的发送消息请求"""
        群号 = 数据.get('group_id')
        用户id = 数据.get('user_id')
        消息内容 = 数据.get('message', '')

        if 群号:
            await self._发送至onebot(int(群号), 消息内容)
        elif 用户id:
            请求网址 = f"{self.onebot_api_地址}/send_private_msg"
            请求负载 = {
                "message_type": "private",
                "user_id": int(用户id),
                "message": 消息内容
            }

            try:
                async with self._会话.post(请求网址, json=请求负载) as 响应:
                    await 响应.json()
            except Exception as 异常:
                logger.error(f"[HermesAdapter] 发送私聊消息失败: {异常}")

    # ========== HTTP 服务器 ==========

    async def _启动http服务器(self):
        """启动 HTTP 服务器"""
        try:
            应用实例 = web.Application()
            应用实例.router.add_post('/api/execute', self._处理执行指令)
            应用实例.router.add_post('/api/send', self._处理发送消息)
            应用实例.router.add_get('/api/health', self._处理健康检查)
            应用实例.router.add_get('/api/stats', self._处理统计)
            应用实例.router.add_get('/api/commands', self._处理列出指令)
            应用实例.router.add_get('/api/commands/for_hermes', self._处理hermes指令列表)
            应用实例.router.add_get('/api/command/{command_name}', self._处理指令详情)

            self._http_运行器 = web.AppRunner(应用实例)
            await self._http_运行器.setup()
            self._http_站点 = web.TCPSite(self._http_运行器, '0.0.0.0', self.http_服务器_端口)
            await self._http_站点.start()

            logger.info(f"[HermesAdapter] HTTP 服务器已启动: http://0.0.0.0:{self.http_服务器_端口}")
        except Exception as 异常:
            logger.error(f"[HermesAdapter] 启动 HTTP 服务器失败: {异常}")

    async def _停止http服务器(self):
        """停止 HTTP 服务器"""
        if self._http_站点:
            await self._http_站点.stop()
        if self._http_运行器:
            await self._http_运行器.cleanup()

    def _验证认证(self, 请求: web.Request) -> bool:
        """验证请求认证"""
        if not self.http_服务器_令牌:
            return True
        认证头部 = 请求.headers.get('Authorization', '')
        if 认证头部.startswith('Bearer '):
            return 认证头部[7:] == self.http_服务器_令牌
        return 请求.query.get('token', '') == self.http_服务器_令牌

    async def _处理健康检查(self) -> web.Response:
        """健康检查接口"""
        return web.json_response({
            'status': 'ok',
            'service': 'hermes_adapter',
            'timestamp': time.time(),
            'ws_connected': self._ws_已连接,
            'commands_cached': len(self._处理器缓存),
            'groups_cached': list(self._群组事件.keys())
        })

    async def _处理统计(self, 请求: web.Request) -> web.Response:
        """统计信息接口"""
        if not self._验证认证(请求):
            return web.json_response({'error': 'Unauthorized'}, status=401)

        return web.json_response({
            'stats': self.统计数据,
            'uptime_seconds': time.time() - self.统计数据['start_time'],
            'ws_connected': self._ws_已连接,
            'groups_cached': list(self._群组事件.keys())
        })

    async def _处理列出指令(self, 请求: web.Request) -> web.Response:
        """列出可执行的指令"""
        if not self._验证认证(请求):
            return web.json_response({'error': 'Unauthorized'}, status=401)

        指令集合 = {}
        for 指令名称, 处理器信息 in self._处理器缓存.items():
            插件名称 = 处理器信息['plugin']
            if 插件名称 not in 指令集合:
                指令集合[插件名称] = []
            指令集合[插件名称].append({
                'command': 指令名称,
                'description': 处理器信息['description'],
                'aliases': 处理器信息['aliases'],
                'is_admin': 处理器信息['is_admin']
            })

        return web.json_response({'total': len(self._处理器缓存), 'commands': 指令集合})

    async def _处理hermes指令列表(self, 请求: web.Request) -> web.Response:
        """为 Hermes 提供指令列表"""
        if not self._验证认证(请求):
            return web.json_response({'error': 'Unauthorized'}, status=401)

        if not self._处理器缓存:
            self._构建处理器缓存()

        # 指令分类映射
        分类映射 = {
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

        指令列表 = []
        分类字典 = {}

        for 指令名称, 处理器信息 in self._处理器缓存.items():
            插件名称 = 处理器信息['plugin']
            指令描述 = 处理器信息['description']
            别名集合 = 处理器信息['aliases']
            是否管理员指令 = 处理器信息['is_admin']

            所属分类 = '其他'
            for 分类, 关键词 in 分类映射.items():
                if any(kw in 指令名称 or kw in 指令描述 for kw in 关键词):
                    所属分类 = 分类
                    break
                for 别名 in 别名集合:
                    if any(kw in 别名 for kw in 关键词):
                        所属分类 = 分类
                        break

            用法 = 指令名称
            if 别名集合:
                用法 = f"{指令名称} (别名: {', '.join(别名集合[:3])})"

            指令信息 = {
                'name': 指令名称,
                'description': 指令描述,
                'usage': 用法,
                'aliases': 别名集合,
                'plugin': 插件名称,
                'is_admin': 是否管理员指令,
                'category': 所属分类
            }

            指令列表.append(指令信息)

            if 所属分类 not in 分类字典:
                分类字典[所属分类] = []
            分类字典[所属分类].append(指令名称)

        排序后的分类 = dict(sorted(分类字典.items()))

        return web.json_response({
            'total': len(指令列表),
            'categories': 排序后的分类,
            'commands': 指令列表,
            'usage_hint': '使用 POST /api/execute 执行指令，格式: {"command": "指令名", "args": "参数", "group_id": "群号"}'
        })

    async def _处理指令详情(self, 请求: web.Request) -> web.Response:
        """获取单个指令的详细信息"""
        if not self._验证认证(请求):
            return web.json_response({'error': 'Unauthorized'}, status=401)

        指令名称 = 请求.match_info.get('command_name', '')

        if not self._处理器缓存:
            self._构建处理器缓存()

        实际指令 = self._别名到指令.get(指令名称, 指令名称)
        处理器信息 = self._处理器缓存.get(实际指令)

        if not 处理器信息:
            return web.json_response({
                'error': f'未找到指令: {指令名称}',
                'available_commands': list(self._处理器缓存.keys())[:20]
            }, status=404)

        return web.json_response({
            'command': 实际指令,
            'description': 处理器信息['description'],
            'aliases': 处理器信息['aliases'],
            'plugin': 处理器信息['plugin'],
            'is_admin': 处理器信息['is_admin'],
            'usage_example': f'POST /api/execute {{"command": "{实际指令}", "args": "参数", "group_id": "群号"}}'
        })

    async def _处理执行指令(self, 请求: web.Request) -> web.Response:
        """执行 AstrBot 指令接口"""
        if not self._验证认证(请求):
            return web.json_response({'error': 'Unauthorized'}, status=401)

        try:
            数据 = await 请求.json()
            提取命令 = 数据.get('command', '').strip()
            提取参数 = 数据.get('args', '').strip()
            群号 = 数据.get('group_id', '')
            用户id = 数据.get('user_id', 'hermes_agent')
            用户名 = 数据.get('user_name', 'Hermes Agent')

            if not 提取命令:
                return web.json_response({'success': False, 'error': '缺少必需参数: command'}, status=400)

            可执行, 原因 = self._检查能否执行指令(提取命令)
            if not 可执行:
                return web.json_response({'success': False, 'error': 原因}, status=403)

            if not self._处理器缓存:
                self._构建处理器缓存()

            if 提取命令.startswith('/'):
                提取命令 = 提取命令[1:]
            实际指令 = self._别名到指令.get(提取命令, 提取命令)

            处理器信息 = self._处理器缓存.get(实际指令)
            if not 处理器信息:
                return web.json_response({'success': False, 'error': f'未找到指令: {提取命令}'}, status=404)

            执行结果 = await self._内部执行指令(
                处理器信息=处理器信息,
                指令=实际指令,
                参数列表=提取参数,
                用户id=用户id,
                用户名=用户名,
                群号=群号
            )

            self.统计数据['commands_executed'] += 1

            return web.json_response({
                'success': True,
                'command': 实际指令,
                'args': 提取参数,
                'result': 执行结果
            })

        except json.JSONDecodeError:
            return web.json_response({'success': False, 'error': '无效的 JSON 格式'}, status=400)
        except Exception as 异常:
            self.统计数据['errors'] += 1
            logger.error(f"[HermesAdapter] 执行指令失败: {异常}", exc_info=True)
            return web.json_response({'success': False, 'error': str(异常)}, status=500)

    async def _内部执行指令(
        self,
        处理器信息: Dict,
        指令: str,
        参数列表: str = '',
        用户id: str = 'hermes_agent',
        用户名: str = 'Hermes Agent',
        群号: str = ''
    ) -> Dict[str, Any]:
        """内部执行指令方法"""
        try:
            处理器: StarHandlerMetadata = 处理器信息['handler']

            if 参数列表:
                消息字符串 = f"{指令} {参数列表}"
            else:
                消息字符串 = 指令

            已存事件 = self._群组事件.get(群号) if 群号 else None

            if 已存事件:

                事件对象 = copy.copy(已存事件)
                事件对象.message_str = 消息字符串

                astrbot消息 = AstrBotMessage()
                astrbot消息.group_id = 群号
                astrbot消息.self_id = 已存事件.message_obj.self_id
                astrbot消息.sender = MessageMember(user_id=用户id, nickname=用户名)
                astrbot消息.type = MessageType.GROUP_MESSAGE
                astrbot消息.session_id = 已存事件.session_id
                astrbot消息.message_id = str(int(time.time() * 1000) % 2147483647)
                astrbot消息.message = [Plain(text=消息字符串)]
                astrbot消息.message_str = 消息字符串
                astrbot消息.raw_message = {}
                astrbot消息.timestamp = int(time.time())

                事件对象.message_obj = astrbot消息
            else:
                logger.warning(f"[HermesAdapter] 群 {群号} 没有存储的 event，使用模拟对象")

                qq平台 = None
                for platform in self.context.platform_manager.platform_insts:
                    if hasattr(platform, 'get_client'):
                        qq平台 = platform
                        break

                if not qq平台:
                    return {'texts': [], 'images': [], 'success': False, 'error': '未找到 QQ 平台适配器'}

                机器人实例 = qq平台.get_client()
                平台元数据 = qq平台.meta()

                astrbot消息 = AstrBotMessage()
                astrbot消息.self_id = str(平台元数据.id)
                astrbot消息.sender = MessageMember(user_id=用户id, nickname=用户名)
                astrbot消息.type = MessageType.GROUP_MESSAGE
                astrbot消息.session_id = f"group_{群号}" if 群号 else f"hermes_{用户id}"
                astrbot消息.group_id = 群号
                astrbot消息.message_id = str(int(time.time() * 1000) % 2147483647)
                astrbot消息.message = [Plain(text=消息字符串)]
                astrbot消息.message_str = 消息字符串
                astrbot消息.raw_message = {}
                astrbot消息.timestamp = int(time.time())

                事件对象 = AiocqhttpMessageEvent(
                    message_str=消息字符串,
                    message_obj=astrbot消息,
                    platform_meta=平台元数据,
                    session_id=astrbot消息.session_id,
                    bot=机器人实例
                )

            结果文本列表 = []
            结果图片列表 = []
            已发消息 = []

            logger.info(f"[HermesAdapter] 开始执行指令: {指令}, 参数: {参数列表}")
            logger.info(f"[HermesAdapter] 处理器: {处理器信息['plugin']} - {处理器信息['command']}")

            try:
                结果数量 = 0
                async for 执行结果 in 处理器.handler(事件对象):
                    结果数量 += 1
                    logger.info(f"[HermesAdapter] 收到结果 #{结果数量}: {type(执行结果)}")

                    if 执行结果 is not None:
                        # 尝试通过 OneBot API 发送结果
                        if 群号:
                            try:
                                # 检查是否是 JSON 组件（音乐卡片等）
                                if hasattr(执行结果, 'chain') and 执行结果.chain:
                                    for 组件 in 执行结果.chain:
                                        if isinstance(组件, Json):
                                            # JSON 组件，直接发送
                                            json数据 = 组件.data if hasattr(组件, 'data') else {}
                                            if json数据:
                                                # 通过 OneBot API 发送 JSON 消息
                                                onebot消息内容 = [{"type": "json", "data": {"data": json.dumps(json数据)}}]
                                                发送返回 = await self._发送cq码至onebot(int(群号), onebot消息内容)
                                                已发消息.append(发送返回)
                                                logger.info(f"[HermesAdapter] 已通过 OneBot 发送 JSON 消息")
                                        elif hasattr(组件, 'text') and 组件.text:
                                            # 文本组件，直接发送
                                            发送返回 = await self._发送至onebot(int(群号), 组件.text)
                                            已发消息.append(发送返回)
                                            logger.info(f"[HermesAdapter] 已通过 OneBot 发送文本: {组件.text[:50]}...")
                                        elif isinstance(组件, Image):
                                            # 图片组件
                                            if hasattr(组件, 'url') and 组件.url:
                                                onebot消息内容 = [{"type": "image", "data": {"file": 组件.url}}]
                                                发送返回 = await self._发送cq码至onebot(int(群号), onebot消息内容)
                                                已发消息.append(发送返回)
                                                logger.info(f"[HermesAdapter] 已通过 OneBot 发送图片")
                            except Exception as 发送错误:
                                logger.error(f"[HermesAdapter] OneBot 发送失败: {发送错误}", exc_info=True)

                        # 收集内容用于返回
                        if hasattr(执行结果, 'chain') and 执行结果.chain:
                            for 组件 in 执行结果.chain:
                                logger.info(f"[HermesAdapter] 组件类型: {type(组件).__name__}")
                                if hasattr(组件, 'text') and 组件.text:
                                    结果文本列表.append(str(组件.text))
                                elif isinstance(组件, Image):
                                    if hasattr(组件, 'url') and 组件.url:
                                        结果图片列表.append(str(组件.url))
                                elif isinstance(组件, Json):
                                    logger.info(f"[HermesAdapter] Json 组件")

                logger.info(f"[HermesAdapter] 执行完成，共 {结果数量} 个结果")
            except TypeError as 类型错误:
                logger.warning(f"[HermesAdapter] 异步生成器失败，尝试同步调用: {类型错误}")
                执行结果 = await 处理器.handler(事件对象)
                if 执行结果 is not None:
                    if hasattr(执行结果, 'chain') and 执行结果.chain:
                        for 组件 in 执行结果.chain:
                            if hasattr(组件, 'text') and 组件.text:
                                结果文本列表.append(str(组件.text))
                            elif isinstance(组件, Image):
                                if hasattr(组件, 'url') and 组件.url:
                                    结果图片列表.append(str(组件.url))
            except Exception as 异常:
                logger.error(f"[HermesAdapter] 执行指令异常: {异常}", exc_info=True)

            return {
                'texts': 结果文本列表,
                'images': 结果图片列表,
                'sent_messages': len(已发消息),
                'success': True
            }

        except Exception as 异常:
            logger.error(f"[HermesAdapter] 内部执行指令失败: {异常}", exc_info=True)
            return {'texts': [], 'images': [], 'success': False, 'error': str(异常)}

    # ========== 消息监听和转发 ==========

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AiocqhttpMessageEvent):
        """监听群消息，存储 event 并转发给 Hermes"""
        消息内容 = event.get_message_str()
        群号 = event.get_group_id()
        用户id = event.get_sender_id()
        用户名 = event.get_sender_name()


        if 群号:
            self._群组事件[群号] = event
            logger.debug(f"[HermesAdapter] 已存储群 {群号} 的 event 对象")

        应转发, 消息内容 = self._是否应转发(消息内容, 群号, 用户id, event)
        if not 应转发:
            return

        onebot事件体 = self.构造请求体(event, 消息内容, 群号, 用户id, 用户名)
        logger.debug(f"转发的消息体：{onebot事件体}")

        await self._ws_发送数据(await onebot事件体)
        event.set_extra(self.已转发键, True)
        self.统计数据['messages_forwarded'] += 1
        logger.info(f"[HermesAdapter] 已转发[{用户名}] 的消息到 Hermes：{消息内容[:50]}")

    async def 构造请求体(self, event: AiocqhttpMessageEvent, 消息内容: str, 群号: str, 用户id: str, 用户名: str) -> dict:
        """
        构造 OneBot v11 格式的群消息事件体。

        将接收到的 Aiocqhttp 消息事件转换为符合 OneBot v11 标准的事件字典，
        用于后续消息处理或转发。内部会处理消息 ID 的重复问题、消息长度截断，
        并提取原始消息链以构建完整的事件结构。

        Args:
            event: Aiocqhttp 消息事件对象，包含原始消息数据和扩展信息。
            消息内容: 待构造的消息文本内容（可能被截断）。
            群号: 群号的字符串表示，将被转换为整数放入 `group_id` 字段。
            用户id: 发送者用户 ID 的字符串表示，将被转换为整数放入 `user_id` 及 `sender.user_id`。
            用户名: 发送者昵称，同时用于 `sender.nickname` 和 `sender.card`。

        Returns:
            符合 OneBot v11 规范的群消息事件字典，结构如下：
            {
                "time": int,           # 当前时间戳
                "self_id": "astrbot",  # 固定为 "astrbot"
                "post_type": "message",
                "message_type": "group",
                "sub_type": "normal",
                "message_id": int,     # 原始或随机生成的消息 ID
                "group_id": int,
                "user_id": int,
                "message": list,       # 经 `_parse_onebot_json` 转换后的消息链
                "raw_message": str,    # 原始消息文本
                "font": 0,
                "sender": {
                    "user_id": int,
                    "nickname": str,
                    "card": str
                }
            }

        Notes:
            - 如果事件扩展信息中标记了“已转发”（通过 `self.已转发键` 判断），
              会使用随机 ID（基于时间戳）以避免重复；否则尝试从 `event.message_obj.message_id` 获取原始 ID。
            - 当获取原始 ID 失败时，同样生成随机 ID，并记录错误日志。
            - 若 `消息内容` 长度超过 `self.最大消息长度`，则截断并添加 `...[已截断]` 后缀。
            - 函数内部会调用 `event._parse_onebot_json` 将消息链转换为 OneBot 格式。
        """
        # ... 函数实现 ...
        if event.get_extra(self.已转发键, False):
            消息id = int(time.time() * 1000) % 2147483647
            # 不能重复使用相同id，否则会被忽略， 但是消息id有用途，所有保留使用原始id
            logger.warning(f"消息已转发过，将使用随机id：{消息内容[:50]}")
        else:
            try:
                消息id = int(event.message_obj.message_id)
            except Exception as e:
                消息id = int(time.time() * 1000) % 2147483647
                logger.error(f"获取消息id失败：{e}")

        if len(消息内容) > self.最大消息长度:
            消息内容 = 消息内容[:self.最大消息长度] + '...[已截断]'

        原始消息链 = event.get_messages()  # 假设返回的是 List[MessageSegment]

        # 删除所有 Plain 类型的元素，保留其他类型
        新消息链 = [seg for seg in 原始消息链 if not isinstance(seg, Plain)]

        # 追加新的 Plain 内容
        新消息链.append(Plain(text=消息内容))
        # 构建 OneBot v11 格式的事件消息
        onebot事件体 = {
            "time": int(time.time()),
            "self_id": "astrbot",
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": 消息id,
            "group_id": int(群号),
            "user_id": int(用户id),
            "message": await event._parse_onebot_json(MessageChain(chain=新消息链)),
            "raw_message": event.message_obj.raw_message,
            "font": 0,
            "sender": {
                "user_id": int(用户id),
                "nickname": 用户名,
                "card": 用户名
            }
        }

        return onebot事件体

    def _检查approve_deny授权(self, 用户id: str) -> bool:
        """检查用户是否有 /approve 或 /deny 的权限"""
        if self.approve_deny_允许用户:
            if 用户id in self.approve_deny_允许用户:
                return True
        return False

    def _是否应转发(self, 消息内容: str, 群号: str, 用户id: str, event: AiocqhttpMessageEvent) -> tuple[bool, str]:
        """判断是否需要转发给 Hermes"""
        # 1. 转发所有消息
        if self.转发所有消息:
            logger.debug(f"[HermesAdapter] 转发消息（原因：转发所有消息），内容：{消息内容[:30]}...")
            return True, 消息内容

        # 2. 群组白名单过滤
        if self.允许的群组 and 群号 not in self.允许的群组:
            logger.debug(f"[HermesAdapter] 忽略消息（原因：群号 {群号} 不在允许的群组列表中）")
            return False, 消息内容

        # 3. 用户白名单过滤
        if self.允许的用户 and 用户id not in self.允许的用户:
            logger.debug(f"[HermesAdapter] 忽略消息（原因：用户 {用户id} 不在允许的用户列表中）")
            return False, 消息内容

        名字 = self.触发关键词[0] if self.触发关键词 else ""

        # 4. /approve 和 /deny 命令处理
        if self.approve_deny_启用 and 消息内容.startswith(("approve", "deny")):
            # 检查是否为原始 "/" 命令（因 AstrBot 会去掉前缀）
            if next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith("/"):
                if not self._检查approve_deny授权(用户id):
                    logger.info(f"[HermesAdapter] /approve 或 /deny 被拒绝: 用户 {用户id} 无权限")
                    return False, 消息内容
                logger.debug(f"[HermesAdapter] 转发消息（原因：approve/deny 授权命令），用户：{用户id}")
                return True, f"/{消息内容}\n{名字}"

        # 5. @ 机器人触发
        if self.触发艾特机器人:
            消息列表 = event.get_messages()
            for 单条消息 in 消息列表:
                if isinstance(单条消息, At):
                    机器人id = event.get_self_id()
                    if str(单条消息.qq) == str(机器人id):
                        logger.debug(f"[HermesAdapter] 转发消息（原因：@ 机器人触发），内容：{消息内容[:30]}...")
                        return True, 名字 + "，" + 消息内容

        # 6. 关键词触发
        for 关键词 in self.触发关键词:
            if 关键词.lower() in 消息内容.lower():
                logger.debug(f"[HermesAdapter] 转发消息（原因：命中关键词 '{关键词}'），内容：{消息内容[:30]}...")
                return True, 消息内容

        # 7. 不满足任何条件
        logger.debug(f"[HermesAdapter] 忽略消息（原因：不满足任何转发条件），内容：{消息内容[:30]}...")
        return False, 消息内容

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

        ws状态文本 = "✅ 已连接" if self._ws_已连接 else "❌ 未连接"

        输出行 = [
            '📡 Hermes 适配器状态 (WebSocket 版本)',
            f'运行时间: {小时数}小时{分钟数}分钟',
            f'WebSocket: {ws状态文本}',
            f'已缓存指令: {len(self._处理器缓存)}个',
            f'已缓存群: {len(self._群组事件)}个',
            f'转发消息: {self.统计数据["messages_forwarded"]}条',
            f'执行指令: {self.统计数据["commands_executed"]}次',
            f'错误次数: {self.统计数据["errors"]}次',
            f'重连次数: {self.统计数据["ws_reconnects"]}次',
            '',
            f'Hermes WebSocket: {self.hermes_ws_链接}',
            f'HTTP 服务器: http://localhost:{self.http_服务器_端口}',
            f'已缓存群列表: {", ".join(self._群组事件.keys()) or "无"}',
        ]

        yield event.plain_result('\n'.join(输出行))

    @hermes_cmd.command("test")
    async def cmd_test(self, event: AiocqhttpMessageEvent):
        """测试与 Hermes 的连接"""
        if self._ws_已连接:
            yield event.plain_result('✅ WebSocket 已连接到 Hermes')
        else:
            yield event.plain_result('❌ WebSocket 未连接')

    # ========== LLM 工具 ==========

    @filter.llm_tool("hermes_agent")
    async def hermes_agent(
        self,
        event: AiocqhttpMessageEvent,
        task: str,
        command: str = "",
        args: str = "",
    ) -> str:
        """
        调用 Hermes Agent 执行任务或命令。Hermes 是一个强大的 AI Agent，可以执行各种复杂任务。
        当用户需要执行复杂任务、查询信息、处理数据、调用其他插件功能时，可以使用此工具。

        Args:
            task(string): 任务描述，详细说明需要完成什么任务
            command(string): 具体要执行的 AstrBot 指令（可选，如 "点歌"、"群分析" 等）
            args(string): 指令参数（可选，如歌曲名、群号等）
        """
        try:
            # 如果没有指定群号，使用当前群
            group_id = event.get_group_id()

            # 如果有具体指令，直接执行
            if command:
                logger.info(f"[HermesAdapter] LLM工具执行指令: {command} {args}")

                # 检查指令是否允许执行
                可执行, 原因 = self._检查能否执行指令(command)
                if not 可执行:
                    return f"指令执行被拒绝: {原因}"

                # 构建处理器缓存（如果需要）
                if not self._处理器缓存:
                    self._构建处理器缓存()

                # 查找指令
                实际指令 = self._别名到指令.get(command, command)
                处理器信息 = self._处理器缓存.get(实际指令)

                if not 处理器信息:
                    可用指令 = list(self._处理器缓存.keys())[:20]
                    return f"未找到指令: {command}。可用指令: {', '.join(可用指令)}"

                # 执行指令
                执行结果 = await self._内部执行指令(
                    处理器信息=处理器信息,
                    指令=实际指令,
                    参数列表=args,
                    用户id=event.get_sender_id(),
                    用户名=event.get_sender_name(),
                    群号=group_id
                )

                if 执行结果.get('success'):
                    文本集合 = 执行结果.get('texts', [])
                    图片集合 = 执行结果.get('images', [])

                    结果部分 = []
                    if 文本集合:
                        结果部分.append("执行结果:\n" + "\n".join(文本集合))
                    if 图片集合:
                        结果部分.append(f"生成了 {len(图片集合)} 张图片")

                    return "\n".join(结果部分) if 结果部分 else "指令执行成功"
                else:
                    return f"指令执行失败: {执行结果.get('error', '未知错误')}"

            # 如果没有具体指令，但有任务描述，使用OneBot格式发送给Hermes
            else:
                logger.info(f"[HermesAdapter] LLM工具执行任务: {task}")

                # 检查 WebSocket 连接
                if not self._ws_已连接:
                    return "Hermes Agent 未连接，请稍后再试"

                # 获取触发关键词（名字）
                名字 = self.触发关键词[0] if self.触发关键词 else "纳西妲"

                # 构建带名字的消息内容
                消息内容 = f"{名字}，{task}"

                # 构建 OneBot v11 格式的事件消息
                用户id = event.get_sender_id()
                用户名 = event.get_sender_name()

                onebot事件体 = self.构造请求体(event, 消息内容, group_id, 用户id, 用户名)

                logger.debug(f"[HermesAdapter] LLM工具发送OneBot格式消息: {onebot事件体}")

                # 通过 WebSocket 发送 OneBot 格式的消息
                await self._ws_发送数据(await onebot事件体)
                event.set_extra(self.已转发键, True)
                self.统计数据['messages_forwarded'] += 1

                return f"已向 Hermes Agent 发送任务: {task}。Hermes 会自主完成任务并回复结果。"

        except Exception as 异常:
            logger.error(f"[HermesAdapter] LLM工具执行失败: {异常}", exc_info=True)
            return f"执行失败: {str(异常)}"

    @filter.llm_tool("hermes_status")
    async def hermes_status(self, _: AiocqhttpMessageEvent) -> str:
        """
        查询 Hermes Agent 和适配器的运行状态。
        当用户询问 Hermes 是否在线、连接状态、已缓存指令数量等信息时使用。

        Returns:
            str: 状态信息，包括连接状态、运行时间、统计信息等
        """
        运行耗时 = time.time() - self.统计数据['start_time']
        小时数 = int(运行耗时 // 3600)
        分钟数 = int((运行耗时 % 3600) // 60)

        ws状态 = "已连接" if self._ws_已连接 else "未连接"

        状态信息 = [
            f"Hermes 适配器状态:",
            f"- WebSocket 连接: {ws状态}",
            f"- 运行时间: {小时数}小时{分钟数}分钟",
            f"- 已缓存指令: {len(self._处理器缓存)}个",
            f"- 已缓存群: {len(self._群组事件)}个",
            f"- 已转发消息: {self.统计数据['messages_forwarded']}条",
            f"- 已执行指令: {self.统计数据['commands_executed']}次",
            f"- 错误次数: {self.统计数据['errors']}次"
        ]

        return "\n".join(状态信息)

    @filter.llm_tool("hermes_list_commands")
    async def hermes_list_commands(self, _: AiocqhttpMessageEvent, category: str = "") -> str:
        """
        列出所有可通过 Hermes 执行的 AstrBot 指令。
        当用户想知道有哪些指令可用、或者需要查找特定功能的指令时使用。

        Args:
            category (str): 指令分类过滤（可选），如 "音乐"、"宠物"、"好感度" 等

        Returns:
            str: 指令列表，按分类组织
        """
        # 构建处理器缓存（如果需要）
        if not self._处理器缓存:
            self._构建处理器缓存()

        # 指令分类映射
        分类映射 = {
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

        # 按分类整理指令
        分类字典 = {}
        for 指令名称, 处理器信息 in self._处理器缓存.items():
            插件名称 = 处理器信息['plugin']
            指令描述 = 处理器信息['description']
            别名集合 = 处理器信息['aliases']
            是否管理员指令 = 处理器信息['is_admin']

            所属分类 = '其他'
            for 分类, 关键词 in 分类映射.items():
                if any(kw in 指令名称 or kw in 指令描述 for kw in 关键词):
                    所属分类 = 分类
                    break
                for 别名 in 别名集合:
                    if any(kw in 别名 for kw in 关键词):
                        所属分类 = 分类
                        break

            # 如果指定了分类，只返回该分类的指令
            if category and 所属分类 != category:
                continue

            if 所属分类 not in 分类字典:
                分类字典[所属分类] = []

            用法 = 指令名称
            if 别名集合:
                用法 = f"{指令名称} (别名: {', '.join(别名集合[:3])})"

            指令信息 = {
                'name': 指令名称,
                'description': 指令描述,
                'usage': 用法,
                'plugin': 插件名称,
                'is_admin': 是否管理员指令
            }

            分类字典[所属分类].append(指令信息)

        # 构建输出
        输出行 = []
        for 分类, 指令列表 in sorted(分类字典.items()):
            输出行.append(f"\n【{分类}】")
            for 指令 in 指令列表[:10]:  # 每个分类最多显示10个
                管理员标记 = " [管理员]" if 指令['is_admin'] else ""
                输出行.append(f"  - {指令['usage']}: {指令['description']}{管理员标记}")

        if not 输出行:
            if category:
                return f"没有找到分类为 '{category}' 的指令"
            else:
                return "没有找到可用指令"

        return f"可用指令列表 (共{len(self._处理器缓存)}个):" + "\n".join(输出行)

    #有一些难以解决的问题，先不使用
    # @hermes_cmd.command("execute")
    # async def cmd_execute(self, event: AiocqhttpMessageEvent,*, command):
    #     """手动执行 Hermes 指令"""
    #     logger.info(f"接收到的参数：{command}")
    #     切割部分 = command.split(maxsplit=1)
    #     提取命令 = 切割部分[0]
    #     提取参数 = 切割部分[1] if len(切割部分) > 1 else ''
    #
    #     yield event.plain_result(f'正在执行指令: {提取命令} {提取参数}')
    #
    #     if not self._处理器缓存:
    #         self._构建处理器缓存()
    #
    #     if 提取命令.startswith('/'):
    #         提取命令 = 提取命令[1:]
    #     实际指令 = self._别名到指令.get(提取命令, 提取命令)
    #
    #     处理器信息 = self._处理器缓存.get(实际指令)
    #     if not 处理器信息:
    #         yield event.plain_result(f'❌ 未找到指令: {提取命令}')
    #         return
    #
    #     执行结果 = await self._内部执行指令(
    #         处理器信息=处理器信息,
    #         指令=实际指令,
    #         参数列表=提取参数,
    #         用户id=event.get_sender_id(),
    #         用户名=event.get_sender_name(),
    #         群号=event.get_group_id()
    #     )
    #
    #     if 执行结果.get('success'):
    #         文本集合 = 执行结果.get('texts', [])
    #         if 文本集合:
    #             yield event.plain_result('\n'.join(文本集合))
    #         else:
    #             yield event.plain_result('✅ 指令执行成功')
    #     else:
    #         yield event.plain_result(f'❌ 执行失败: {执行结果.get("error", "未知错误")}')