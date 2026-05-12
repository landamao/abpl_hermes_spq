"""
OneBot API 客户端模块

封装所有与 OneBot HTTP API 的交互：发送消息、上传文件、表情回应、API 请求路由。
"""
import aiohttp
from typing import Dict, Any, Optional
from astrbot.api.all import logger


class OneBotClient:
    """OneBot HTTP API 客户端"""

    def __init__(self, session: aiohttp.ClientSession, api_url: str, token: str = ""):
        self._session = session
        self._api_url = api_url.rstrip('/')
        self._token = token
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    # ========== 消息发送 ==========

    async def send_group_text(self, group_id: int, text: str) -> dict:
        """发送文本消息到群"""
        return await self._post("/send_group_msg", {
            "message_type": "group",
            "group_id": group_id,
            "message": text
        })

    async def send_group_cq(self, group_id: int, message: list) -> dict:
        """发送 CQ 码 / 富媒体消息到群"""
        return await self._post("/send_group_msg", {
            "message_type": "group",
            "group_id": group_id,
            "message": message
        })

    async def send_private_text(self, user_id: int, text: str) -> dict:
        """发送私聊消息"""
        return await self._post("/send_private_msg", {
            "message_type": "private",
            "user_id": user_id,
            "message": text
        })

    async def upload_group_file(self, group_id: int, file_path: str, name: str = "") -> dict:
        """上传文件到群"""
        return await self._post("/upload_group_file", {
            "group_id": group_id,
            "file": file_path,
            "name": name or file_path.split("/")[-1].split("\\")[-1]
        })

    async def upload_private_file(self, user_id: int, file_path: str, name: str = "") -> dict:
        """上传文件到私聊"""
        return await self._post("/upload_private_file", {
            "user_id": user_id,
            "file": file_path,
            "name": name or file_path.split("/")[-1].split("\\")[-1]
        })

    async def set_msg_emoji_like(self, message_id: str | int, emoji_id: str | int = 12) -> dict:
        """给消息贴表情回应"""
        return await self._post("/set_msg_emoji_like", {
            "message_id": message_id,
            "emoji_id": emoji_id,
            "set": True
        })

    # ========== API 请求路由（处理 Hermes 通过 WS 发来的 API 请求） ==========

    async def handle_api_request(self, data: dict, send_fn, send_cq_fn) -> Dict[str, Any]:
        """
        处理 Hermes 的 OneBot API 请求，路由到对应的 API 调用。

        Args:
            data: WebSocket 收到的请求数据
            send_fn: 发送群文本消息的函数 (group_id, text) -> dict
            send_cq_fn: 发送群 CQ 消息的函数 (group_id, message_list) -> dict

        Returns:
            API 响应结果
        """
        action = data.get('action', '')
        params = data.get('params', {})

        logger.info(f"[Hermes适配器] 收到 API 请求: {action}, echo={data.get('echo', '')}")

        try:
            if action == 'send_group_msg':
                group_id = params.get('group_id')
                message = params.get('message', '')
                if isinstance(message, list):
                    result = await send_cq_fn(group_id, message)
                else:
                    result = await send_fn(group_id, message)
                if result and 'retcode' in result:
                    return result
                elif result and 'status' not in result:
                    return {"status": "ok", "retcode": 0, "data": result, "msg": ""}
                return result

            elif action == 'send_private_msg':
                result = await self._post("/send_private_msg", {
                    "message_type": "private",
                    "user_id": params.get('user_id'),
                    "message": params.get('message', '')
                })
                return result

            elif action == 'get_group_info':
                return await self._get("/get_group_info", {"group_id": params.get('group_id')})

            elif action == 'get_msg':
                return await self._get("/get_msg", {"message_id": params.get('message_id')})

            elif action == 'set_msg_emoji_like':
                return await self._post("/set_msg_emoji_like", {
                    "message_id": params.get('message_id'),
                    "emoji_id": params.get('emoji_id', 12),
                    "set": params.get('set', True)
                })

            elif action == 'send_forward_msg':
                return await self._post("/send_forward_msg", {
                    "messages": params.get('messages', [])
                })

            elif action == 'send_group_forward_msg':
                return await self._post("/send_group_forward_msg", {
                    "group_id": params.get('group_id'),
                    "messages": params.get('messages', [])
                })

            elif action == 'get_group_list':
                return await self._get("/get_group_list")

            elif action == 'get_group_member_info':
                return await self._get("/get_group_member_info", {
                    "group_id": params.get('group_id'),
                    "user_id": params.get('user_id')
                })

            elif action == 'friend_poke':
                return await self._get("/friend_poke", {"user_id": params.get('user_id')})

            elif action == 'upload_group_file':
                return await self._post("/upload_group_file", {
                    "group_id": params.get('group_id'),
                    "file": params.get('file', ''),
                    "name": params.get('name', '')
                })

            elif action == 'upload_private_file':
                return await self._post("/upload_private_file", {
                    "user_id": params.get('user_id'),
                    "file": params.get('file', ''),
                    "name": params.get('name', '')
                })

            else:
                logger.warning(f"[Hermes适配器] 未支持的 API 操作: {action}")
                logger.debug(f"原始数据：{data}")
                return {"status": "failed", "retcode": 100, "msg": f"未支持的操作: {action}", "data": None}

        except Exception as e:
            logger.error(f"[Hermes适配器] API 调用失败: {action} - {e}", exc_info=True)
            return {"status": "failed", "retcode": 100, "msg": str(e), "data": None}

    @staticmethod
    def build_api_response(result: dict, echo: str) -> Optional[dict]:
        """构建 OneBot 格式的 API 响应"""
        if not echo:
            return None
        return {
            "status": result.get("status", "failed"),
            "retcode": result.get("retcode", 0),
            "data": result.get("data"),
            "msg": result.get("msg", ""),
            "echo": echo
        }

    # ========== 敏感字符过滤 ==========

    @staticmethod
    def filter_sensitive(text: str, sensitive_list: list, replacement: str) -> str:
        """对文本进行敏感字符过滤替换"""
        if not sensitive_list or not text:
            return text
        for keyword in sensitive_list:
            if keyword:
                text = text.replace(keyword, replacement)
        return text

    # ========== 内部方法 ==========

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._api_url}{path}"
        try:
            logger.debug(f"[Hermes适配器] OneBot POST {path}: {payload}")
            async with self._session.post(url, json=payload, headers=self._headers) as resp:
                result = await resp.json()
                logger.debug(f"[Hermes适配器] OneBot POST {path} 结果: {result}")
                return result
        except Exception as e:
            logger.error(f"[Hermes适配器] OneBot POST {path} 失败: {e}", exc_info=True)
            return {"error": str(e)}

    async def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self._api_url}{path}"
        try:
            async with self._session.get(url, params=params, headers=self._headers) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"[Hermes适配器] OneBot GET {path} 失败: {e}", exc_info=True)
            return {"error": str(e)}
