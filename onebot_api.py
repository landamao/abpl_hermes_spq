"""
OneBot API 模块

负责通过 OneBot HTTP API 发送消息，以及处理 Hermes 发来的 API 请求。
"""
import aiohttp
from typing import Dict, Any, Optional
from astrbot.api.all import logger


async def send_text(session: aiohttp.ClientSession, onebot_url: str, 群号: int, 消息内容: str) -> dict:
    """通过 OneBot API 发送文本消息到群"""
    url = f"{onebot_url}/send_group_msg"
    payload = {
        "message_type": "group",
        "group_id": 群号,
        "message": 消息内容
    }
    try:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            logger.info(f"[HermesAdapter] OneBot 发送结果: {result}")
            return result
    except Exception as e:
        logger.error(f"[HermesAdapter] OneBot 发送失败: {e}")
        return {"error": str(e)}


async def send_cq(session: aiohttp.ClientSession, onebot_url: str, 群号: int, 消息内容: list) -> dict:
    """通过 OneBot API 发送 CQ 码格式消息"""
    url = f"{onebot_url}/send_group_msg"
    payload = {
        "message_type": "group",
        "group_id": 群号,
        "message": 消息内容
    }
    try:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            logger.info(f"[HermesAdapter] OneBot CQ 发送结果: {result}")
            return result
    except Exception as e:
        logger.error(f"[HermesAdapter] OneBot CQ 发送失败: {e}")
        return {"error": str(e)}


async def send_private(session: aiohttp.ClientSession, onebot_url: str, 用户id, 消息内容: str) -> dict:
    """通过 OneBot API 发送私聊消息"""
    url = f"{onebot_url}/send_private_msg"
    payload = {
        "message_type": "private",
        "user_id": 用户id,
        "message": 消息内容
    }
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception as e:
        logger.error(f"[HermesAdapter] 发送私聊消息失败: {e}")
        return {"error": str(e)}


async def handle_api_request(
    数据: dict,
    session: aiohttp.ClientSession,
    onebot_url: str,
    send_fn,
    send_cq_fn
) -> Dict[str, Any]:
    """
    处理 Hermes 的 OneBot API 请求。

    Args:
        数据: WebSocket 收到的请求数据
        session: aiohttp 会话
        onebot_url: OneBot API 地址
        send_fn: 发送文本消息的函数 (群号, 内容) -> dict
        send_cq_fn: 发送 CQ 码的函数 (群号, 内容) -> dict

    Returns:
        API 响应结果
    """
    动作 = 数据.get('action', '')
    参数 = 数据.get('params', {})

    logger.info(f"[HermesAdapter] 收到 API 请求: {动作}, echo={数据.get('echo', '')}")

    try:
        if 动作 == 'send_group_msg':
            群号 = 参数.get('group_id')
            消息内容 = 参数.get('message', '')
            if isinstance(消息内容, list):
                结果 = await send_cq_fn(群号, 消息内容)
            else:
                结果 = await send_fn(群号, 消息内容)
            if 结果 and 'retcode' in 结果:
                return 结果
            elif 结果 and 'status' not in 结果:
                return {"status": "ok", "retcode": 0, "data": 结果, "msg": ""}
            return 结果

        elif 动作 == 'send_private_msg':
            url = f"{onebot_url}/send_private_msg"
            payload = {
                "message_type": "private",
                "user_id": 参数.get('user_id'),
                "message": 参数.get('message', '')
            }
            async with session.post(url, json=payload) as resp:
                return await resp.json()

        elif 动作 == 'get_group_info':
            url = f"{onebot_url}/get_group_info"
            async with session.get(url, params={"group_id": 参数.get('group_id')}) as resp:
                return await resp.json()

        elif 动作 == 'get_msg':
            url = f"{onebot_url}/get_msg"
            async with session.get(url, params={"message_id": 参数.get('message_id')}) as resp:
                return await resp.json()

        elif 动作 == 'set_msg_emoji_like':
            url = f"{onebot_url}/set_msg_emoji_like"
            payload = {
                "message_id": 参数.get('message_id'),
                "emoji_id": 参数.get('emoji_id', 12),
                "set": 参数.get('set', True)
            }
            async with session.post(url, json=payload) as resp:
                return await resp.json()

        elif 动作 == 'send_forward_msg':
            url = f"{onebot_url}/send_forward_msg"
            async with session.post(url, json={"messages": 参数.get('messages', [])}) as resp:
                return await resp.json()

        elif 动作 == 'send_group_forward_msg':
            url = f"{onebot_url}/send_group_forward_msg"
            payload = {"group_id": 参数.get('group_id'), "messages": 参数.get('messages', [])}
            async with session.post(url, json=payload) as resp:
                return await resp.json()

        elif 动作 == 'get_group_list':
            url = f"{onebot_url}/get_group_list"
            async with session.get(url) as resp:
                return await resp.json()

        elif 动作 == 'get_group_member_info':
            url = f"{onebot_url}/get_group_member_info"
            params = {"group_id": 参数.get('group_id'), "user_id": 参数.get('user_id')}
            async with session.get(url, params=params) as resp:
                return await resp.json()
        elif 动作 == 'friend_poke':
            url = f"{onebot_url}/friend_poke"
            params = {"user_id":参数.get('user_id')}
            async with session.get(url, params=params) as resp:
                return await resp.json()
        else:
            logger.warning(f"[HermesAdapter] 未支持的 API 操作: {动作}")
            logger.debug(f"原始数据：{数据}")
            return {"status": "failed", "retcode": 100, "msg": f"未支持的操作: {动作}", "data": None}

    except Exception as e:
        logger.error(f"[HermesAdapter] API 调用失败: {动作} - {e}", exc_info=True)
        return {"status": "failed", "retcode": 100, "msg": str(e), "data": None}


def build_api_response(结果数据: dict, 回声字段: str) -> Optional[dict]:
    """
    构建 OneBot 格式的 API 响应。

    Args:
        结果数据: API 调用结果
        回声字段: echo 字段

    Returns:
        响应字典（如果需要发送），否则 None
    """
    if not 回声字段:
        return None
    return {
        "status": 结果数据.get("status", "failed"),
        "retcode": 结果数据.get("retcode", 0),
        "data": 结果数据.get("data"),
        "msg": 结果数据.get("msg", ""),
        "echo": 回声字段
    }
