"""
WebSocket 客户端模块

负责与 Hermes Agent 的 WebSocket 连接管理、消息收发。
"""
import json
import asyncio
import websockets
from astrbot.api.all import logger

from .onebot_api import handle_api_request, build_api_response, send_text, send_cq


async def ws_connect(adapter):
    """连接到 Hermes WebSocket 并监听消息"""
    headers = {}
    if adapter.hermes_访问令牌:
        headers['Authorization'] = f'Bearer {adapter.hermes_访问令牌}'

    logger.info(f"[HermesAdapter] 正在连接到 Hermes: {adapter.hermes_ws_链接}")

    async with websockets.connect(
        adapter.hermes_ws_链接,
        additional_headers=headers,
        ping_interval=20,
        ping_timeout=60
    ) as ws:
        adapter.ws_连接 = ws
        adapter.ws_已连接 = True
        adapter.重连延迟 = 1.0

        logger.info("[HermesAdapter] WebSocket 已连接到 Hermes")

        await _send_connect(adapter)

        async for msg in ws:
            try:
                await _handle_message(adapter, msg)
            except Exception as e:
                logger.error(f"[HermesAdapter] 处理 WebSocket 消息失败: {e}", exc_info=True)


async def ws_loop(adapter):
    """WebSocket 重连循环"""
    while True:
        try:
            await ws_connect(adapter)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[HermesAdapter] WebSocket 连接异常: {e}", exc_info=True)

        if adapter.ws_已连接:
            adapter.ws_已连接 = False
            logger.info("[HermesAdapter] WebSocket 断开，准备重连...")

        adapter.统计数据['ws_reconnects'] += 1
        logger.info(f"[HermesAdapter] 等待 {adapter.重连延迟:.1f}s 后重连...")
        await asyncio.sleep(adapter.重连延迟)
        adapter.重连延迟 = min(adapter.重连延迟 * 2, adapter.最大重连延迟)


async def ws_send(adapter, 数据: dict):
    """发送 WebSocket 消息"""
    if adapter.ws_连接 and adapter.ws_已连接:
        try:
            await adapter.ws_连接.send(json.dumps(数据, ensure_ascii=False))
        except Exception as e:
            logger.error(f"[HermesAdapter] WebSocket 发送失败: {e}", exc_info=True)
            logger.debug(f"[HermesAdapter] 发送失败，原始数据: {数据}")
            adapter.ws_已连接 = False


async def _send_connect(adapter):
    """发送连接确认消息"""
    await ws_send(adapter, {
        "type": "connect",
        "platform": "qq",
        "self_id": "astrbot",
        "data": {}
    })


async def _handle_message(adapter, 原始消息: str):
    """处理从 Hermes 收到的 WebSocket 消息"""
    try:
        数据 = json.loads(原始消息)
        消息类型 = 数据.get('type', '')

        if 消息类型 == 'api_request':
            await _handle_api(adapter, 数据)
        elif 消息类型 == 'send_message':
            await _handle_send_message(adapter, 数据)
        elif 消息类型 == 'ping':
            await ws_send(adapter, {"type": "pong"})
        elif 'action' in 数据:
            await _handle_api(adapter, 数据)

    except json.JSONDecodeError:
        logger.error(f"[HermesAdapter] 无效的 JSON 消息: {原始消息[:200]}", exc_info=True)
    except Exception as e:
        logger.error(f"[HermesAdapter] 处理消息失败: {e}", exc_info=True)


async def _handle_api(adapter, 数据: dict):
    """处理 API 请求并发送响应"""
    回声字段 = 数据.get('echo', '')

    async def send_fn(群号, 内容):
        return await send_text(adapter.会话, adapter.onebot_api_地址, 群号, 内容)

    async def send_cq_fn(群号, 内容):
        return await send_cq(adapter.会话, adapter.onebot_api_地址, 群号, 内容)

    结果 = await handle_api_request(数据, adapter.会话, adapter.onebot_api_地址, send_fn, send_cq_fn)

    # 记录发送的消息 ID
    if isinstance(结果, dict):
        message_id = 结果.get("data", {}).get("message_id")
        if message_id:
            adapter.记录hermes消息id(message_id)
            logger.debug(f"[HermesAdapter] API 请求发送消息记录 ID: {message_id}")

    响应 = build_api_response(结果, 回声字段)
    if 响应:
        await ws_send(adapter, 响应)


async def _handle_send_message(adapter, 数据: dict):
    """处理 Hermes 的发送消息请求"""
    群号 = 数据.get('group_id')
    用户id = 数据.get('user_id')
    消息内容 = 数据.get('message', '')

    if 群号:
        result = await send_text(adapter.会话, adapter.onebot_api_地址, int(群号), 消息内容)
        message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
        adapter.记录hermes消息id(message_id)
    elif 用户id:
        from .onebot_api import send_private
        result = await send_private(adapter.会话, adapter.onebot_api_地址, int(用户id), 消息内容)
        message_id = result.get("data", {}).get("message_id") if isinstance(result, dict) else None
        adapter.记录hermes消息id(message_id)
