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

from .command_cache import check_command_allowed, resolve_command, categorize_commands


def verify_auth(请求: web.Request, token: str) -> bool:
    """验证请求认证"""
    if not token:
        return True
    auth = 请求.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:] == token
    return 请求.query.get('token', '') == token


async def handle_health(adapter) -> web.Response:
    """健康检查"""
    return web.json_response({
        'status': 'ok',
        'service': 'hermes_adapter',
        'timestamp': time.time(),
        'ws_connected': adapter.ws_已连接,
        'commands_cached': len(adapter.处理器缓存),
        'groups_cached': list(adapter.群组事件.keys())
    })


async def handle_stats(请求: web.Request, adapter) -> web.Response:
    """统计信息"""
    if not verify_auth(请求, adapter.http_服务器_令牌):
        return web.json_response({'error': 'Unauthorized'}, status=401)
    return web.json_response({
        'stats': adapter.统计数据,
        'uptime_seconds': time.time() - adapter.统计数据['start_time'],
        'ws_connected': adapter.ws_已连接,
        'groups_cached': list(adapter.群组事件.keys())
    })


async def handle_list_commands(请求: web.Request, adapter) -> web.Response:
    """列出可执行的指令"""
    if not verify_auth(请求, adapter.http_服务器_令牌):
        return web.json_response({'error': 'Unauthorized'}, status=401)
    指令集合 = {}
    for 指令名称, 处理器信息 in adapter.处理器缓存.items():
        插件名称 = 处理器信息['plugin']
        if 插件名称 not in 指令集合:
            指令集合[插件名称] = []
        指令集合[插件名称].append({
            'command': 指令名称,
            'description': 处理器信息['description'],
            'aliases': 处理器信息['aliases'],
            'is_admin': 处理器信息['is_admin']
        })
    return web.json_response({'total': len(adapter.处理器缓存), 'commands': 指令集合})


async def handle_hermes_commands(请求: web.Request, adapter) -> web.Response:
    """为 Hermes 提供指令列表（带分类）"""
    if not verify_auth(请求, adapter.http_服务器_令牌):
        return web.json_response({'error': 'Unauthorized'}, status=401)
    if not adapter.处理器缓存:
        adapter.rebuild_cache()
    分类字典 = categorize_commands(adapter.处理器缓存)
    指令列表 = []
    for 分类, items in 分类字典.items():
        指令列表.extend(items)
    排序后的分类 = {k: [i['name'] for i in v] for k, v in sorted(分类字典.items())}
    return web.json_response({
        'total': len(指令列表),
        'categories': 排序后的分类,
        'commands': 指令列表,
        'usage_hint': '使用 POST /api/execute 执行指令，格式: {"command": "指令名", "args": "参数", "group_id": "群号"}'
    })


async def handle_command_detail(请求: web.Request, adapter) -> web.Response:
    """获取单个指令的详细信息"""
    if not verify_auth(请求, adapter.http_服务器_令牌):
        return web.json_response({'error': 'Unauthorized'}, status=401)
    指令名称 = 请求.match_info.get('command_name', '')
    if not adapter.处理器缓存:
        adapter.rebuild_cache()
    处理器信息 = resolve_command(指令名称, adapter.别名到指令, adapter.处理器缓存)
    if not 处理器信息:
        return web.json_response({
            'error': f'未找到指令: {指令名称}',
            'available_commands': list(adapter.处理器缓存.keys())[:20]
        }, status=404)
    实际指令 = adapter.别名到指令.get(指令名称, 指令名称)
    return web.json_response({
        'command': 实际指令,
        'description': 处理器信息['description'],
        'aliases': 处理器信息['aliases'],
        'plugin': 处理器信息['plugin'],
        'is_admin': 处理器信息['is_admin'],
        'usage_example': f'POST /api/execute {{"command": "{实际指令}", "args": "参数", "group_id": "群号"}}'
    })


async def handle_execute(请求: web.Request, adapter) -> web.Response:
    """执行 AstrBot 指令"""
    if not verify_auth(请求, adapter.http_服务器_令牌):
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

        可执行, 原因 = check_command_allowed(提取命令, adapter.指令白名单, adapter.指令黑名单)
        if not 可执行:
            return web.json_response({'success': False, 'error': 原因}, status=403)

        if not adapter.处理器缓存:
            adapter.rebuild_cache()

        处理器信息 = resolve_command(提取命令, adapter.别名到指令, adapter.处理器缓存)
        if not 处理器信息:
            return web.json_response({'success': False, 'error': f'未找到指令: {提取命令}'}, status=404)

        执行结果 = await execute_command(adapter, 处理器信息, 提取参数, 用户id, 用户名, 群号)
        adapter.统计数据['commands_executed'] += 1

        return web.json_response({
            'success': True,
            'command': adapter.别名到指令.get(提取命令.lstrip('/'), 提取命令),
            'args': 提取参数,
            'result': 执行结果
        })
    except json.JSONDecodeError:
        return web.json_response({'success': False, 'error': '无效的 JSON 格式'}, status=400)
    except Exception as e:
        adapter.统计数据['errors'] += 1
        logger.error(f"[HermesAdapter] 执行指令失败: {e}", exc_info=True)
        return web.json_response({'success': False, 'error': str(e)}, status=500)


async def execute_command(adapter, 处理器信息: Dict, 参数列表: str = '',
                          用户id: str = 'hermes_agent', 用户名: str = 'Hermes Agent',
                          群号: str = '') -> Dict[str, Any]:
    """内部执行指令方法"""
    try:
        处理器 = 处理器信息['handler']
        指令名称 = 处理器信息['command']

        if 参数列表:
            消息字符串 = f"{指令名称} {参数列表}"
        else:
            消息字符串 = 指令名称

        已存事件 = adapter.群组事件.get(群号) if 群号 else adapter.私聊事件.get(用户id)

        if 已存事件:
            事件对象 = copy.copy(已存事件)
            事件对象.message_str = 消息字符串
            astrbot消息 = _build_astrbot_message(
                群号=群号, self_id=已存事件.message_obj.self_id,
                用户id=用户id, 用户名=用户名,
                session_id=已存事件.session_id, 消息字符串=消息字符串
            )
            事件对象.message_obj = astrbot消息
        else:
            logger.warning(f"[HermesAdapter] 群 {群号} 没有存储的 event，使用模拟对象")
            事件对象 = _build_simulated_event(adapter, 消息字符串, 群号, 用户id, 用户名)
            if isinstance(事件对象, dict):
                return 事件对象

        结果文本列表 = []
        结果图片列表 = []
        已发消息 = []

        logger.info(f"[HermesAdapter] 开始执行指令: {指令名称}, 参数: {参数列表}")

        try:
            结果数量 = 0
            handler_result = 处理器.handler(事件对象)
            
            # 判断是异步生成器还是协程
            if hasattr(handler_result, '__aiter__'):
                # 异步生成器：用 async for 遍历
                async for 执行结果 in handler_result:
                    结果数量 += 1
                    if 执行结果 is not None:
                        if 群号:
                            try:
                                await _send_result_to_group(adapter, int(群号), 执行结果, 已发消息)
                            except Exception as send_err:
                                logger.error(f"[HermesAdapter] OneBot 发送失败: {send_err}", exc_info=True)
                        _collect_result(执行结果, 结果文本列表, 结果图片列表)
            else:
                # 协程：用 await 调用
                执行结果 = await handler_result
                结果数量 = 1
                if 执行结果 is not None:
                    if 群号:
                        try:
                            await _send_result_to_group(adapter, int(群号), 执行结果, 已发消息)
                        except Exception as send_err:
                            logger.error(f"[HermesAdapter] OneBot 发送失败: {send_err}", exc_info=True)
                    _collect_result(执行结果, 结果文本列表, 结果图片列表)
            
            logger.info(f"[HermesAdapter] 执行完成，共 {结果数量} 个结果")
        except TypeError as 类型错误:
            logger.warning(f"[HermesAdapter] 异步生成器失败，尝试同步调用: {类型错误}")
            执行结果 = await 处理器.handler(事件对象)
            if 执行结果 is not None:
                _collect_result(执行结果, 结果文本列表, 结果图片列表)
        except Exception as e:
            logger.error(f"[HermesAdapter] 执行指令异常: {e}", exc_info=True)

        return {'texts': 结果文本列表, 'images': 结果图片列表, 'sent_messages': len(已发消息), 'success': True}
    except Exception as e:
        logger.error(f"[HermesAdapter] 内部执行指令失败: {e}", exc_info=True)
        return {'texts': [], 'images': [], 'success': False, 'error': str(e)}


def _build_astrbot_message(群号, self_id, 用户id, 用户名, session_id, 消息字符串):
    msg = AstrBotMessage()
    msg.group_id = 群号
    msg.self_id = self_id
    msg.sender = MessageMember(user_id=用户id, nickname=用户名)
    msg.type = MessageType.GROUP_MESSAGE
    msg.session_id = session_id
    msg.message_id = str(int(time.time() * 1000) % 2147483647)
    msg.message = [Plain(text=消息字符串)]
    msg.message_str = 消息字符串
    msg.raw_message = {}
    msg.timestamp = int(time.time())
    return msg


def _build_simulated_event(adapter, 消息字符串, 群号, 用户id, 用户名):
    qq平台 = None
    for platform in adapter.context.platform_manager.platform_insts:
        if hasattr(platform, 'get_client'):
            qq平台 = platform
            break
    if not qq平台:
        return {'texts': [], 'images': [], 'success': False, 'error': '未找到 QQ 平台适配器'}
    机器人实例 = qq平台.get_client()
    平台元数据 = qq平台.meta()
    astrbot消息 = _build_astrbot_message(
        群号=群号, self_id=str(平台元数据.id),
        用户id=用户id, 用户名=用户名,
        session_id=f"group_{群号}" if 群号 else f"hermes_{用户id}",
        消息字符串=消息字符串
    )
    return AiocqhttpMessageEvent(
        message_str=消息字符串, message_obj=astrbot消息,
        platform_meta=平台元数据, session_id=astrbot消息.session_id, bot=机器人实例
    )


async def _send_result_to_group(adapter, 群号: int, 执行结果, 已发消息: list):
    from .onebot_api import send_text, send_cq
    if not hasattr(执行结果, 'chain') or not 执行结果.chain:
        return
    for 组件 in 执行结果.chain:
        if isinstance(组件, Json):
            json数据 = 组件.data if hasattr(组件, 'data') else {}
            if json数据:
                onebot消息内容 = [{"type": "json", "data": {"data": json.dumps(json数据)}}]
                result = await send_cq(adapter.会话, adapter.onebot_api_地址, 群号, onebot消息内容)
                已发消息.append(result)
                message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
                adapter.记录hermes消息id(message_id)
                logger.debug(f"[HermesAdapter] 已通过 OneBot 发送 JSON, message_id={message_id}")
        elif hasattr(组件, 'text') and 组件.text:
            result = await send_text(adapter.会话, adapter.onebot_api_地址, 群号, 组件.text)
            已发消息.append(result)
            message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
            adapter.记录hermes消息id(message_id)
            logger.debug(f"[HermesAdapter] 已通过 OneBot 发送文本, message_id={message_id}")
        elif isinstance(组件, Image):
            if hasattr(组件, 'url') and 组件.url:
                onebot消息内容 = [{"type": "image", "data": {"file": 组件.url}}]
                result = await send_cq(adapter.会话, adapter.onebot_api_地址, 群号, onebot消息内容)
                已发消息.append(result)
                message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
                adapter.记录hermes消息id(message_id)
                logger.debug(f"[HermesAdapter] 已通过 OneBot 发送图片, message_id={message_id}")


def _collect_result(执行结果, 文本列表: list, 图片列表: list):
    if not hasattr(执行结果, 'chain') or not 执行结果.chain:
        return
    for 组件 in 执行结果.chain:
        if hasattr(组件, 'text') and 组件.text:
            文本列表.append(str(组件.text))
        elif isinstance(组件, Image):
            if hasattr(组件, 'url') and 组件.url:
                图片列表.append(str(组件.url))


async def start_http_server(adapter):
    """启动 HTTP 服务器并注册路由"""
    try:
        app = web.Application()
        app.router.add_post('/api/execute', lambda r: handle_execute(r, adapter))
        app.router.add_get('/api/health', lambda r: handle_health(adapter))
        app.router.add_get('/api/stats', lambda r: handle_stats(r, adapter))
        app.router.add_get('/api/commands', lambda r: handle_list_commands(r, adapter))
        app.router.add_get('/api/commands/for_hermes', lambda r: handle_hermes_commands(r, adapter))
        app.router.add_get('/api/command/{command_name}', lambda r: handle_command_detail(r, adapter))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', adapter.http_服务器_端口)
        await site.start()
        adapter.http_运行器 = runner
        adapter.http_站点 = site
        logger.info(f"[HermesAdapter] HTTP 服务器已启动: http://0.0.0.0:{adapter.http_服务器_端口}")
    except Exception as e:
        logger.error(f"[HermesAdapter] 启动 HTTP 服务器失败: {e}")


async def stop_http_server(adapter):
    """停止 HTTP 服务器"""
    if adapter.http_站点:
        await adapter.http_站点.stop()
    if adapter.http_运行器:
        await adapter.http_运行器.cleanup()
