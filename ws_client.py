import json, asyncio,websockets
from .napcat_send import NapCatSend
from .status import Status
from .logger import logger

class WsClient:

    def __init__(self, hermes_ws_url, hermes_token, napcat_send:NapCatSend):
        self.ws已连接 = False
        self.ws重连延迟 = 5
        self.NapCatSend = napcat_send
        self.ws任务 = None
        self.hermes_ws_url = hermes_ws_url
        self.hermes_token = hermes_token
        self.ws服务 = None
        self.机器人qq = "纳西妲"
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
                Status.ws发送成功 += 1
                logger.debug(f"[Hermes适配器] 已发送数据到Hermes：{data}")
            except Exception as e:
                Status.ws发送失败 += 1
                logger.error(f"[Hermes适配器] WebSocket 发送失败: {e}", exc_info=True)
                logger.error(f"[Hermes适配器] 发送失败，原始数据: {data}")

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
                logger.info("[Hermes适配器] WebSocket 断开，准备重连...")
                self.ws已连接 = False
                Status.ws断开次数 += 1
    
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

            logger.info("[Hermes适配器] WebSocket 已连接到 Hermes")
            logger.info(f"[Hermes适配器] 机器人qq：{self.机器人qq}")
            self.ws已连接 = True
            Status.ws连接次数 += 1

            await self.发送ws消息({
                "type": "connect",
                "platform": "qqonebot",
                "self_id": self.机器人qq,
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
        Status.ws收到消息 += 1
        logger.debug(f"[Hermes适配器] 转发来自Hermes的消息到NapCat的数据：{data}")
        结果 = await self.NapCatSend.发送data消息到NapCat(data)
        logger.debug(f"[Hermes适配器] 转发来自Hermes的消息到NapCat的结果：{结果}")
        await self.发送ws消息(结果)
