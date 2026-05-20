from aiohttp import web
from urllib.parse import urlparse
from . import logger
from .napcat_send import NapCatSend
from .status import HermesStatus


class ReverseHTTPServer:
    """反向HTTP服务器"""

    def __init__(self, napcat_send: NapCatSend, config: dict):
        连接配置: dict = config['连接配置']
        self.napcat_send = napcat_send
        self.地址: str = 连接配置['反向HTTP地址'].strip()
        self.令牌: str = 连接配置['反向HTTP令牌'].strip()
        self.端口: int = int(连接配置.get('反向HTTP端口', 5701))
        self._runner = None

    async def _处理请求(self, request: web.Request) -> web.Response:
        # 鉴权
        if self.令牌:
            token = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
            if token != self.令牌:
                return web.json_response(
                    {"status": "error", "msg": "Unauthorized"}, status=401)

        # 解析请求体
        try:
            body = await request.json()
        except Exception:
            body = {}

        # 从URL路径提取action: /send_msg -> send_msg
        action = request.match_info.get('action', '').strip('/')
        if not action:
            return web.json_response(
                {"status": "error", "msg": "Missing action in URL path"}, status=400)

        echo = body.pop('echo', None)
        params = body

        logger.info(f"[Hermes适配器] 反向HTTP收到请求: {action}")
        logger.debug(f"[Hermes适配器] 反向HTTP请求参数: {params}")

        # 通过 NapCatSend 转发到 NapCat
        try:
            data = {"action": action, "params": params, "echo": echo}
            result = await self.napcat_send.发送data消息到NapCat(data)
            HermesStatus.反向HTTP请求 += 1
            logger.debug(f"[Hermes适配器] 反向HTTP转发结果: {result}")
            return web.json_response(result)
        except Exception as e:
            HermesStatus.反向HTTP失败 += 1
            logger.error(f"[Hermes适配器] 反向HTTP转发失败: {e}", exc_info=True)
            return web.json_response({
                "status": "failed", "retcode": -1,
                "data": None, "msg": str(e), "echo": echo}, status=500)

    async def start(self):
        """启动反向HTTP服务器"""
        app = web.Application()

        async def health_handler(_: web.Request) -> web.Response:
            return web.json_response({"status": "ok", "msg": "Hermes适配器反向HTTP服务器运行中"})

        app.router.add_get('/api/health', health_handler)
        app.router.add_route('*', '/{action:.*}', self._处理请求)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        host = urlparse(self.地址).hostname or '0.0.0.0'
        site = web.TCPSite(self._runner, host, self.端口)
        try:
            await site.start()
            logger.info(f"[Hermes适配器] 反向HTTP服务器已启动: http://{host}:{self.端口}")
            logger.info(f"[Hermes适配器] Hermes应将请求发送到: http://127.0.0.1:{self.端口}/<action>")
        except OSError as e:
            logger.error(f"[Hermes适配器] 反向HTTP服务器启动失败: {e}", exc_info=True)
            await self._runner.cleanup()
            self._runner = None

    async def stop(self):
        """停止反向HTTP服务器"""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("[Hermes适配器] 反向HTTP服务器已停止")
