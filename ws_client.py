import json, asyncio,websockets
import time
from .napcat_send import NapCatSend
from .status import Status
from .logger import logger

class WsClient:

    def __init__(self, hermes_ws_url, hermes_token, napcat_send:NapCatSend,
                 重连间隔: float = 5, 最大重连次数: int = 0):
        self.指令重启 = False
        self.发送类型 = None
        self.目标ID = None
        self.ws已连接 = False
        # 重连配置：间隔（秒）与上限（0 表示无限）
        try:
            self.ws重连延迟 = max(1.0, float(重连间隔))
        except (TypeError, ValueError):
            self.ws重连延迟 = 5.0
        try:
            self.最大重连次数 = max(0, int(最大重连次数))
        except (TypeError, ValueError):
            self.最大重连次数 = 0
        self.连续失败次数 = 0
        self.ws自动重连已停止 = False
        self.NapCatSend = napcat_send
        self.ws任务 = None
        self.hermes_ws_url = hermes_ws_url
        self.hermes_token = hermes_token
        self.ws服务 = None
        self.机器人qq = "纳西妲"
        self.重启前时间 = None
        self.重启时event = None
        self.开启连接报告 = False
    # ========== Hermes WebSocket ==========

    async def ws开始(self):
        """启动 WebSocket 连接循环"""
        self.连续失败次数 = 0
        self.ws自动重连已停止 = False
        self.ws任务 = asyncio.create_task(self.ws连接循环())

    async def ws停止(self):
        """停止 WebSocket 连接"""
        if self.ws任务:
            self.ws任务.cancel()
            try:
                await self.ws任务
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"停止 WebSocket 任务时出现异常：{e}")
            self.ws任务 = None
        if self.ws服务:
            try:
                await self.ws服务.close()
            except Exception as e:
                logger.debug(f"关闭 WebSocket 连接时出现异常：{e}")
            self.ws服务 = None
        self.ws已连接 = False

    async def 立即重连(self):
        """手动重连：中断当前连接循环，重置失败计数后立即重新连接"""
        logger.info("收到手动重连请求，正在重建与 Hermes 的连接...")
        await self.ws停止()
        await self.ws开始()

    async def 等待连接(self, 超时: float = 10.0) -> bool:
        """轮询等待连接成功，返回是否在超时前连接成功"""
        截止时间 = time.monotonic() + 超时
        while time.monotonic() < 截止时间:
            if self.ws已连接:
                return True
            await asyncio.sleep(0.2)
        return self.ws已连接

    def 重连状态文本(self) -> str:
        """返回重连配置与当前重连状态的描述"""
        上限 = "无限" if not self.最大重连次数 else f"{self.最大重连次数}次"
        if self.ws自动重连已停止:
            状态 = "已停止（需手动重连）"
        elif self.连续失败次数:
            状态 = f"重连中（已连续失败{self.连续失败次数}次）"
        else:
            状态 = "正常"
        return f"间隔{self.ws重连延迟:.0f}s / 上限{上限} / {状态}"

    async def 发送ws消息(self, data: dict):
        """发送 WebSocket 消息"""
        if self.ws已连接:
            try:
                await self.ws服务.send(json.dumps(data, ensure_ascii=False))
                Status.ws发送成功 += 1
                logger.debug(f"已发送数据到Hermes：{data}")
            except Exception as e:
                Status.ws发送失败 += 1
                logger.error(f"WebSocket 发送失败: {e}", exc_info=True)
                logger.error(f"发送失败，原始数据: {data}")

    async def ws连接循环(self):
        """WebSocket 重连循环（间隔与次数由配置决定）"""
        while True:
            try:
                await self.连接到ws()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WebSocket 连接异常: {e}")

            if self.ws已连接:
                logger.warning("WebSocket 断开，准备重连...")
                self.ws已连接 = False
                Status.ws断开次数 += 1
                # 连接曾成功过，失败计数重新开始
                self.连续失败次数 = 0

            self.连续失败次数 += 1

            if self.最大重连次数 and self.连续失败次数 > self.最大重连次数:
                self.ws自动重连已停止 = True
                logger.error(
                    f"WebSocket 已连续重连失败 {self.最大重连次数} 次，已达上限，停止自动重连。"
                    f"请检查 Hermes 是否运行，修复后可发送指令 /连接Hermes 手动重连"
                )
                break

            if self.最大重连次数:
                logger.info(
                    f"第 {self.连续失败次数}/{self.最大重连次数} 次重连将在 {self.ws重连延迟:.1f}s 后开始..."
                )
            else:
                logger.info(f"第 {self.连续失败次数} 次重连将在 {self.ws重连延迟:.1f}s 后开始...")
            await asyncio.sleep(self.ws重连延迟)

    async def 连接到ws(self):
        """连接到 Hermes WebSocket 并监听消息"""
        头 = {}
        if self.hermes_token:
            头['Authorization'] = f'Bearer {self.hermes_token}'

        logger.info(f"正在连接到 Hermes: {self.hermes_ws_url}")

        async with websockets.connect(
            self.hermes_ws_url,
            additional_headers=头,
            ping_interval=20,
            ping_timeout=60
        ) as ws:
            self.ws服务 = ws

            logger.info("WebSocket 已连接到 Hermes")
            logger.info(f"机器人qq：{self.机器人qq}")
            self.ws已连接 = True
            Status.ws连接次数 += 1
            if self.开启连接报告 or self.重启时event:
                await self._发送连接报告()

            await self.发送ws消息({
                "type": "connect",
                "platform": "qqonebot",
                "self_id": self.机器人qq,
                "data": {}
            })

            async for 原始消息 in ws:
                try:
                    await self.处理ws消息(原始消息)
                    logger.info("收到来自Hermes的消息")
                except Exception as e:
                    logger.error(f"处理 WebSocket 消息失败: {e}", exc_info=True)

    # 在 ws_client.py 的 WsClient 类中添加一个后台任务方法

    async def _转发到NapCat并回响应(self, data: dict):
        """后台任务：转发 Hermes 消息到 NapCat，并将结果发回 Hermes"""
        try:
            result = await self.NapCatSend.发送data消息到NapCat(data)
            logger.debug(f"转发来自Hermes的消息到NapCat的结果：{result}")
            await self.发送ws消息(result)
        except Exception as e:
            logger.error(f"处理 WebSocket 消息失败: {e}", exc_info=True)

    async def 处理ws消息(self, raw):
        data = json.loads(raw)
        Status.ws收到消息 += 1
        # 原日志调用，完全保留
        logger.debug(f"转发来自Hermes的消息到NapCat的数据：{data}")

        # 关键改动：创建后台任务，不再 await，避免阻塞
        asyncio.create_task(self._转发到NapCat并回响应(data))

    def 设置重启状态(self, event):
        self.指令重启 = True
        self.重启前时间 = time.time()
        self.重启时event = event

    async def _发送连接报告(self):
        """发送连接报告"""
        if self.重启前时间:
            重启前时间 = self.重启前时间
            重启耗时 = time.time() - 重启前时间
            连接报告文本 = (
                "✅ Hermes重启完成\n"
                "状态：已连接\n"
                f"重启耗时：{重启耗时:.2f}s"
            )
        else:
            连接报告文本 = (
                "✅ 已连接到Hermes\n"
                f"时间：{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}"
            )
        if self.重启时event:
            event = self.重启时event
            await event.send(event.plain_result(连接报告文本))

        else:
            动作 = "send_msg"
            参数 = {"message": 连接报告文本}
            if self.发送类型 == "群聊":
                参数['group_id'] = self.目标ID
            else:
                参数['user_id'] = self.目标ID
            结果 = await self.NapCatSend.发送动作参数到NapCat(动作, 参数)
            logger.debug(f"连接报告发送结果：{结果}")

        self.重启时event = None
        self.重启前时间 = None
        self.指令重启 = False
