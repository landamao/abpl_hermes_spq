"""
消息处理模块

负责判断消息是否需要转发、构造 OneBot v11 格式事件体。
"""
import time
from astrbot.api.all import logger, Plain, At, Reply, MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


def should_forward(
    event: AiocqhttpMessageEvent,
    消息内容,
    转发所有消息: bool,
    允许的群组: list,
    允许的用户: list,
    触发关键词: list,
    触发艾特机器人: bool,
    approve_启用: bool,
    approve_允许用户: list,
    deny_启用: bool,
    deny_允许用户: list,
    引用hermes消息: bool = False,
) -> bool:
    """
    判断是否需要转发消息给 Hermes。

    Returns:
        (是否应转发, 处理后的消息内容)
    """
    群号 = event.get_group_id()
    用户id = event.get_sender_id()

    # 4. /approve 命令处理
    if approve_启用:
        if (
                (
                消息内容.startswith("approve") and
                next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith("/")
                )
                or 消息内容.startswith("/approve")
        ):
        # if event.get_original_message_str().startswith("/approve"):
            if not _check_approve_deny_permission(用户id, approve_允许用户):
                logger.info(f"[HermesAdapter] /approve 被拒绝: 用户 {用户id} 无权限")
                event.stop_event()
                return False
            logger.debug(f"[HermesAdapter] 转发消息（原因：/approve 授权命令），用户：{用户id}")
            return True

    # 4.5 /deny 命令处理
    if deny_启用:
        if (
                (
                        消息内容.startswith("deny") and
                        next((seg.text for seg in event.get_messages() if isinstance(seg, Plain)), '').strip().startswith(
                            "/")
                )
                or 消息内容.startswith("/deny")
        ):
        # if event.get_original_message_str().startswith("/deny"):
            if not _check_approve_deny_permission(用户id, deny_允许用户):
                logger.info(f"[HermesAdapter] /deny 被拒绝: 用户 {用户id} 无权限")
                event.stop_event()
                return False
            logger.debug(f"[HermesAdapter] 转发消息（原因：/deny 授权命令），用户：{用户id}")
            return True



    # 0. 引用 Hermes 消息直接唤醒
    if 引用hermes消息:
        logger.debug(f"[HermesAdapter] 转发消息（原因：引用 Hermes 消息），内容：{消息内容[:30]}...")
        return True

    # 1. 转发所有消息
    if 转发所有消息:
        logger.debug(f"[HermesAdapter] 转发消息（原因：转发所有消息），内容：{消息内容[:30]}...")
        return True

    # 2. 群组白名单过滤
    if 群号 and 允许的群组 and 群号 not in 允许的群组:
        logger.debug(f"[HermesAdapter] 忽略消息（原因：群号 {群号} 不在允许的群组列表中）")
        return False

    # 3. 用户白名单过滤
    if 允许的用户 and 用户id not in 允许的用户:
        logger.debug(f"[HermesAdapter] 忽略消息（原因：用户 {用户id} 不在允许的用户列表中）")
        return False


    # 5. @ 机器人触发
    if 触发艾特机器人:
        消息链 = event.get_messages()
        自己id = event.get_self_id()
        for 组件 in 消息链:
            if isinstance(组件, At):
                if str(组件.qq) == 自己id:
                    logger.debug(f"[HermesAdapter] 转发消息（原因：@ 机器人触发），内容：{消息内容[:30]}...")
                    return True

    # 6. 关键词触发
    for 关键词 in 触发关键词:
        if 关键词.lower() in 消息内容.lower():
            logger.debug(f"[HermesAdapter] 转发消息（原因：命中关键词 '{关键词}'），内容：{消息内容[:30]}...")
            return True

    # 7. 不满足任何条件
    logger.debug(f"[HermesAdapter] 忽略消息（原因：不满足任何转发条件），内容：{消息内容[:30]}...")
    return False


def _check_approve_deny_permission(用户id: str, 允许用户: list) -> bool:
    """检查用户是否有 /approve 或 /deny 的权限"""
    if 允许用户 and 用户id in 允许用户:
        return True
    return False


async def build_onebot_event(
    event: AiocqhttpMessageEvent,
    消息内容:str,
    最大消息长度: int,
    已转发键: str,
) -> dict:
    """
    构造 OneBot v11 格式的消息事件体（支持群聊和私聊）。
    """
    群号 = event.get_group_id()
    用户id = event.get_sender_id()
    用户名 = event.get_sender_name()
    if event.get_extra(已转发键, False):
        消息id = int(time.time() * 1000) % 2147483647
        logger.warning(f"消息已转发过，将使用随机id：{消息内容[:50]}")
    else:
        try:
            消息id = int(event.message_obj.message_id)
        except Exception as e:
            消息id = int(time.time() * 1000) % 2147483647
            logger.error(f"获取消息id失败，将使用随机id：{e}", exc_info=True)

    if len(消息内容) > 最大消息长度:
        消息内容 = 消息内容[:最大消息长度] + '...[已截断]'

    原始消息链 = event.get_messages()
    新消息链 = [
        seg for seg in 原始消息链
        if not isinstance(seg, Plain) and not isinstance(seg, Reply)
    ]
    新消息链.append(Plain(text=消息内容))
    json后 = await event._parse_onebot_json(MessageChain(chain=新消息链))
    if isinstance(组件 := 原始消息链[0], Reply):
        回复id = 组件.id
        json后.insert(0, {"type": "reply", "data": {"id": str(回复id)}})
    # 基础事件体
    事件体 = {
        "time": int(time.time()),
        "self_id": event.get_self_id(),
        "post_type": "message",
        "message_id": 消息id,
        "user_id": int(用户id),
        "message": json后,
        "raw_message": event.message_obj.raw_message.get("raw_message", 消息内容),
        "font": 0,
        "sender": {
            "user_id": int(用户id),
            "nickname": 用户名,
            "card": 用户名,
        }
    }

    # 根据消息类型添加不同字段
    if 群号:
        事件体["message_type"] = "group"
        事件体["sub_type"] = "normal"
        事件体["group_id"] = int(群号)
        try:
            事件体["sender"]["role"] =  event.message_obj.raw_message['sender']['role']
        except Exception as e:
            logger.warning(f"获取用户 {用户名} 群身份失败\n{e}")
    else:
        事件体["message_type"] = "private"
        事件体["sub_type"] = "friend"
        if 用户名 == "临时会话":
            事件体["sub_type"] = "临时会话"

    return 事件体
