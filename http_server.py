"""
HTTP 服务器模块

负责 HTTP API 端点的处理：健康检查、指令列表、执行指令等。
"""
import json
import time
import copy
from typing import Dict, Any
from aiohttp import web
from astrbot.api.all import (
    logger, Plain, Image, Json,
    AstrBotMessage, MessageMember, MessageType
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


class HttpServer:
    """HTTP API 服务器"""

    def __init__(self, adapter):
        self._adapter = adapter
        self._runner = None
        self._site = None

    async def start(self, host: str, port: int):
        """启动 HTTP 服务器"""
        try:
            app = web.Application()
            app.router.add_post('/api/execute', self._handle_execute)
            app.router.add_get('/api/health', self._handle_health)
            app.router.add_get('/api/stats', self._handle_stats)
            app.router.add_get('/api/commands', self._handle_list_commands)
            app.router.add_get('/api/commands/for_hermes', self._handle_hermes_commands)
            app.router.add_get('/api/command/{command_name}', self._handle_command_detail)

            self._runner = web.AppRunner(app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, host, port)
            await self._site.start()
            logger.info(f"[Hermes适配器] HTTP 服务器已启动: http://{host}:{port}")
        except Exception as e:
            logger.error(f"[Hermes适配器] 启动 HTTP 服务器失败: {e}", exc_info=True)

    async def stop(self):
        """停止 HTTP 服务器"""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    # ========== 认证 ==========

    def _verify_auth(self, request: web.Request) -> bool:
        token = self._adapter.http_服务器_token
        if not token:
            return True
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:] == token
        return request.query.get('token', '') == token

    def _unauthorized(self):
        return web.json_response({'error': 'Unauthorized'}, status=401)

    # ========== 路由处理器 ==========

    async def _handle_health(self, request: web.Request) -> web.Response:
        adapter = self._adapter
        return web.json_response({
            'status': 'ok',
            'service': 'hermes_adapter',
            'timestamp': time.time(),
            'ws_connected': adapter.ws_client.已连接,
            'commands_cached': len(adapter.cmd_manager.处理器缓存),
            'groups_cached': list(adapter.群组事件.keys())
        })

    async def _handle_stats(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        adapter = self._adapter
        return web.json_response({
            'stats': adapter.统计数据,
            'uptime_seconds': time.time() - adapter.统计数据['start_time'],
            'ws_connected': adapter.ws_client.已连接,
            'groups_cached': list(adapter.群组事件.keys())
        })

    async def _handle_list_commands(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        cmd_mgr = self._adapter.cmd_manager
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
        return web.json_response({'total': len(cmd_mgr.处理器缓存), 'commands': commands})

    async def _handle_hermes_commands(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        cmd_mgr = self._adapter.cmd_manager
        if not cmd_mgr.处理器缓存:
            cmd_mgr.rebuild_cache()
        categorized = cmd_mgr.categorize_commands()
        all_commands = []
        for items in categorized.values():
            all_commands.extend(items)
        sorted_categories = {k: [i['name'] for i in v] for k, v in sorted(categorized.items())}
        return web.json_response({
            'total': len(all_commands),
            'categories': sorted_categories,
            'commands': all_commands,
            'usage_hint': '使用 POST /api/execute 执行指令，格式: {"command": "指令名", "args": "参数", "group_id": "群号"}'
        })

    async def _handle_command_detail(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        cmd_mgr = self._adapter.cmd_manager
        command_name = request.match_info.get('command_name', '')
        if not cmd_mgr.处理器缓存:
            cmd_mgr.rebuild_cache()
        handler_info = cmd_mgr.resolve_command(command_name)
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

    async def _handle_execute(self, request: web.Request) -> web.Response:
        if not self._verify_auth(request):
            return self._unauthorized()
        try:
            body = await request.json()
            command = body.get('command', '').strip()
            args = body.get('args', '').strip()
            group_id = body.get('group_id', '')
            user_id = body.get('user_id', 'hermes_agent')
            user_name = body.get('user_name', 'Hermes Agent')

            if not command:
                return web.json_response({'success': False, 'error': '缺少必需参数: command'}, status=400)

            cmd_mgr = self._adapter.cmd_manager
            result = await cmd_mgr.execute_command(command, args, user_id, user_name, group_id)
            self._adapter.统计数据['commands_executed'] += 1

            return web.json_response({
                'success': True,
                'command': cmd_mgr.别名到指令.get(command.lstrip('/'), command),
                'args': args,
                'result': result
            })
        except json.JSONDecodeError:
            return web.json_response({'success': False, 'error': '无效的 JSON 格式'}, status=400)
        except Exception as e:
            self._adapter.统计数据['errors'] += 1
            logger.error(f"[Hermes适配器] 执行指令失败: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)
