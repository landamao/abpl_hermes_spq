"""指令执行 HTTP 服务器

提供 REST API 供 Hermes 调用执行 AstrBot 框架指令。
独立于反向 HTTP 服务器，专门处理指令执行请求。

端点:
    POST /api/execute       执行指令
    GET  /api/health         健康检查
    GET  /api/commands       指令列表
    GET  /api/commands/for_hermes  指令列表（Hermes 专用格式）
    GET  /api/command/{name} 指令详情
"""
import json
import time
from aiohttp import web
from . import logger


class 指令执行HTTP服务器:
    """指令执行 HTTP 服务器"""

    def __init__(self, 指令管理器, napcat_send, config: dict):
        self.指令管理器 = 指令管理器
        self.napcat_send = napcat_send
        self.config = config
        self._runner = None
        self._site = None
        self._start_time = time.time()
        self._execute_count = 0
        self._error_count = 0

    async def start(self, host: str, port: int):
        """启动 HTTP 服务器"""
        try:
            app = web.Application()
            app.router.add_post('/api/execute', self._handle_execute)
            app.router.add_get('/api/health', self._handle_health)
            app.router.add_get('/api/commands', self._handle_list_commands)
            app.router.add_get('/api/commands/for_hermes', self._handle_hermes_commands)
            app.router.add_get('/api/command/{command_name}', self._handle_command_detail)

            self._runner = web.AppRunner(app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, host, port)
            await self._site.start()
            logger.info(f"[Hermes适配器] 指令执行 HTTP 服务器已启动: http://{host}:{port}")
        except Exception as e:
            logger.error(f"[Hermes适配器] 启动指令执行 HTTP 服务器失败: {e}", exc_info=True)

    async def stop(self):
        """停止 HTTP 服务器"""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("[Hermes适配器] 指令执行 HTTP 服务器已停止")

    # ========== 认证 ==========

    def _verify_auth(self, request: web.Request) -> bool:
        token = self.config['指令配置']['http指令服务器token']
        if not token:
            return True
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:] == token
        return request.query.get('token', '') == token

    @staticmethod
    def _unauthorized():
        return web.json_response({'error': 'Unauthorized'}, status=401)

    # ========== 路由处理器 ==========

    async def _handle_health(self, _: web.Request) -> web.Response:
        cmd_mgr = self.指令管理器
        napcat = self.napcat_send
        event = napcat.event[0]
        return web.json_response({
            'status': 'ok',
            'service': 'hermes_adapter_command_server',
            'timestamp': time.time(),
            'commands_cached': len(cmd_mgr.处理器缓存),
            'has_event': event is not None
        })

    async def _handle_execute(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        try:
            body = await request.json()
            command = body.get('command', '').strip()
            args = body.get('args', '').strip()
            group_id = str(body.get('group_id', ''))
            user_id = str(body.get('user_id', 'hermes_agent'))
            user_name = str(body.get('user_name', 'Hermes Agent'))

            if not command:
                return web.json_response(
                    {'success': False, 'error': '缺少必需参数: command'}, status=400)

            self._execute_count += 1
            cmd_mgr = self.指令管理器
            result = await cmd_mgr.执行指令(
                command, args, user_id, user_name, group_id)

            return web.json_response({
                'success': result.get('success', False),
                'command': cmd_mgr.别名到指令.get(command.lstrip('/'), command),
                'args': args,
                'result': result
            })
        except json.JSONDecodeError:
            return web.json_response(
                {'success': False, 'error': '无效的 JSON 格式'}, status=400)
        except Exception as e:
            self._error_count += 1
            logger.error(f"[Hermes适配器] 执行指令失败: {e}", exc_info=True)
            return web.json_response(
                {'success': False, 'error': str(e)}, status=500)

    async def _handle_list_commands(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        cmd_mgr = self.指令管理器
        commands = {}
        for name, info in cmd_mgr.处理器缓存.items():
            plugin = info['plugin']
            if plugin not in commands:
                commands[plugin] = []
            commands[plugin].append({
                'command': name,
                'description': info['description'],
                'aliases': info['aliases'],
                'is_admin': info['is_admin']
            })
        return web.json_response({
            'total': len(cmd_mgr.处理器缓存), 'commands': commands})

    async def _handle_hermes_commands(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        cmd_mgr = self.指令管理器
        if not cmd_mgr.处理器缓存:
            cmd_mgr.重建指令缓存()
        all_commands = []
        for name, info in cmd_mgr.处理器缓存.items():
            all_commands.append({
                'command': name,
                'description': info['description'],
                'plugin': info['plugin'],
                'aliases': info['aliases'],
                'is_admin': info['is_admin']
            })
        return web.json_response({
            'total': len(all_commands),
            'commands': all_commands,
            'usage_hint': '使用 POST /api/execute 执行指令，格式: {"command": "指令名", "args": "参数", "group_id": "群号"}'
        })

    async def _handle_command_detail(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        cmd_mgr = self.指令管理器
        command_name = request.match_info.get('command_name', '')
        if not cmd_mgr.处理器缓存:
            cmd_mgr.重建指令缓存()
        handler_info = cmd_mgr.查找处理器信息(command_name)
        if not handler_info:
            return web.json_response({
                'error': f'未找到指令: {command_name}',
                'available_commands': list(cmd_mgr.处理器缓存.keys())[:20]
            }, status=404)
        actual = cmd_mgr.别名到指令.get(command_name, command_name)
        return web.json_response({
            'command': actual,
            'description': handler_info['description'],
            'aliases': handler_info['aliases'],
            'plugin': handler_info['plugin'],
            'is_admin': handler_info['is_admin'],
            'usage_example': f'POST /api/execute {{"command": "{actual}", "args": "参数", "group_id": "群号"}}'
        })
