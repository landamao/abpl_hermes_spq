"""
WebSocket 客户端模块

负责与 Hermes Agent 的 WebSocket 连接管理、消息收发。
"""
import json
import asyncio
import websockets
from astrbot.api.all import logger
from .onebot_client import OneBotClient


class WebSocketClient:
    """WebSocket 客户端 - 管理与 Hermes 的双向通信"""

    def __init__(self, ws_url: str, token: str,
                 onebot_client: OneBotClient, adapter):
        self._ws_url = ws_url
        self._token = token
        self._onebot = onebot_client
        self._adapter = adapter  # 访问 emoji_manager, 统计数据 等

        self._ws = None
        self._task = None
        self.已连接 = False
        self._重连延迟 = 1.0

    @property
    def connection(self):
        return self._ws

    async def start(self):
        """启动 WebSocket 连接循环"""
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        """停止 WebSocket 连接"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def send(self, data: dict):
        """发送 WebSocket 消息"""
        if self._ws and self.已连接:
            try:
                await self._ws.send(json.dumps(data, ensure_ascii=False))
            except Exception as e:
                logger.error(f"[Hermes适配器] WebSocket 发送失败: {e}", exc_info=True)
                logger.debug(f"[Hermes适配器] 发送失败，原始数据: {data}")
                self.已连接 = False

    # ========== 内部方法 ==========

    async def _loop(self):
        """WebSocket 重连循环"""
        while True:
            try:
                await self._connect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Hermes适配器] WebSocket 连接异常: {e}")

            if self.已连接:
                self.已连接 = False
                logger.info("[Hermes适配器] WebSocket 断开，准备重连...")

            self._adapter.统计数据['ws_reconnects'] += 1
            logger.info(f"[Hermes适配器] 等待 {self._重连延迟:.1f}s 后重连...")
            await asyncio.sleep(self._重连延迟)

    async def _connect(self):
        """连接到 Hermes WebSocket 并监听消息"""
        headers = {}
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'

        logger.info(f"[Hermes适配器] 正在连接到 Hermes: {self._ws_url}")

        async with websockets.connect(
            self._ws_url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=60
        ) as ws:
            self._ws = ws
            self.已连接 = True
            self._重连延迟 = 1.0

            logger.info("[Hermes适配器] WebSocket 已连接到 Hermes")

            await self.send({
                "type": "connect",
                "platform": "qq",
                "self_id": "astrbot",
                "data": {}
            })

            async for msg in ws:
                try:
                    await self._handle_message(msg)
                except Exception as e:
                    logger.error(f"[Hermes适配器] 处理 WebSocket 消息失败: {e}", exc_info=True)

    async def _handle_message(self, raw: str):
        """处理从 Hermes 收到的 WebSocket 消息"""
        try:
            data = json.loads(raw)
            msg_type = data.get('type', '')

            if msg_type == 'api_request':
                await self._handle_api(data)
            elif msg_type == 'send_message':
                await self._handle_send_message(data)
            elif msg_type == 'ping':
                await self.send({"type": "pong"})
            elif 'action' in data:
                await self._handle_api(data)

        except json.JSONDecodeError:
            logger.error(f"[Hermes适配器] 无效的 JSON 消息: {raw[:200]}", exc_info=True)
        except Exception as e:
            logger.error(f"[Hermes适配器] 处理消息失败: {e}", exc_info=True)

    async def _handle_api(self, data: dict):
        """处理 API 请求并发送响应"""
        echo = data.get('echo', '')
        adapter = self._adapter

        # 敏感字符过滤
        params = data.get('params', {})
        if isinstance(params.get('message'), str):
            params['message'] = OneBotClient.filter_sensitive(
                params['message'], adapter.敏感字符列表, adapter.替换目标)
        elif isinstance(params.get('message'), list):
            for seg in params['message']:
                if isinstance(seg, dict) and isinstance(seg.get('data', {}).get('text'), str):
                    seg['data']['text'] = OneBotClient.filter_sensitive(
                        seg['data']['text'], adapter.敏感字符列表, adapter.替换目标)

        async def send_fn(group_id, content):
            return await self._onebot.send_group_text(group_id, content)

        async def send_cq_fn(group_id, content):
            return await self._onebot.send_group_cq(group_id, content)

        result = await self._onebot.handle_api_request(data, send_fn, send_cq_fn)

        # 记录消息 ID 和贴表情
        if isinstance(result, dict):
            message_id = result.get("data", {}).get("message_id")
            adapter.emoji_manager.记录消息id(message_id)
            logger.debug(f"[Hermes适配器] API 请求发送消息记录 ID: {message_id}")
            if adapter.emoji_manager.回复消息贴表情:
                await adapter.emoji_manager.贴表情(self._onebot, message_id)

        response = OneBotClient.build_api_response(result, echo)
        if response:
            await self.send(response)

    async def _handle_send_message(self, data: dict):
        """处理 Hermes 的发送消息请求"""
        adapter = self._adapter
        group_id = data.get('group_id')
        user_id = data.get('user_id')
        message = OneBotClient.filter_sensitive(
            data.get('message', ''), adapter.敏感字符列表, adapter.替换目标)

        if group_id:
            result = await self._onebot.send_group_text(int(group_id), message)
            message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
            adapter.emoji_manager.记录消息id(message_id)
            if adapter.emoji_manager.回复消息贴表情:
                await adapter.emoji_manager.贴表情(self._onebot, message_id)
        elif user_id:
            result = await self._onebot.send_private_text(int(user_id), message)
            message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
            adapter.emoji_manager.记录消息id(message_id)
