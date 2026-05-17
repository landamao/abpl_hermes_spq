"""不依赖其他参数的静态方法"""
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

授权命令映射 = {
    "/同意": "/approve",
    "/一直同意": "/approve always",
    "/会话同意": "/approve session",
    "/拒绝": "/deny"
}

message_id_set:set = set()
记录消息ID = True
最大数量: int = 100000
def madd(mid:int|str|dict) -> None:
    if not 记录消息ID:
        return
    if isinstance(mid, dict):
        if 'message_id' in mid:
            mid = mid['message_id']
        elif 'data' in mid:
            mid = mid['data'].get('message_id')
    elif isinstance(mid, (int, str)):
        mid = str(mid)
    else:
        return
    message_id_set.add(str(mid))
    if len(message_id_set) > 最大数量:
        for _ in range(最大数量//2):
            message_id_set.pop()  # 随机删除一个元素

def mhas(mid:int|str) -> bool:
    return str(mid) in message_id_set

def mclear() -> None:
    message_id_set.clear()

def 用户名(data: dict) -> str:
    """
    从消息数据中提取发送者的显示名称。
    优先使用群名片（card），若为空或不存在则使用昵称（nickname）。
    """
    sender = data.get('sender', {})
    card = sender.get('card', '')
    nickname = sender.get('nickname', '')
    return card or nickname

def 引用ID(data: dict) -> str|None:
    """
    从消息数据中提取回复的消息 ID。
    如果存在回复（type 为 'reply'），返回其 data.id；否则返回 None。
    """
    message_list = data.get('message', [])
    message_id = None
    for segment in message_list:
        if segment.get('type') == 'reply':
            # 回复的 id 可能为字符串或数字，统一转为字符串返回
            message_id = segment.get('data', {}).get('id')
    if message_id:
        return message_id
    return None

def 艾特ID(data: dict) -> list[str]:
    """
    从消息数据中提取所有艾特（type 为 'at'）的 QQ 号。
    返回 QQ 号字符串列表，可能包含 'all'（全体成员）。
    如果没有艾特，返回空列表。
    """
    message_list = data.get('message', [])
    at_list = []
    for segment in message_list:
        if segment.get('type') == 'at':
            qq = segment.get('data', {}).get('qq')
            if qq is not None:
                at_list.append(str(qq))
    return at_list

def all判断(列表:list, lid:str):
    """<说明>"""
    if not 列表:
        return False
    if 列表[0] == "all":
        return True
    return lid in 列表


def 构造文本NapCat事件体(event: AiocqhttpMessageEvent, 文本: str) -> dict:
    """构造包含指定文本的NapCat事件体"""
    raw: dict = dict(event.message_obj.raw_message)
    if raw.get('group_id'):
        return {
            'self_id': raw.get('self_id'),
            'user_id': raw.get('user_id'),
            'time': raw.get('time'),
            'message_id': raw.get('message_id'),
            'message_seq': raw.get('message_seq'),
            'real_id': raw.get('real_id'),
            'real_seq': raw.get('real_seq'),
            'message_type': raw.get('message_type'),
            'sender': raw.get('sender'),
            'raw_message': 文本,
            'font': raw.get('font'),
            'sub_type': raw.get('sub_type'),
            'message': [{'type': 'text', 'data': {'text': 文本}}],
            'message_format': raw.get('message_format'),
            'post_type': raw.get('post_type'),
            'group_id': raw.get('group_id'),
            'group_name': raw.get('group_name'),
        }

    else:
        return {
            'self_id': raw.get('self_id'),
            'user_id': raw.get('user_id'),
            'time': raw.get('time'),
            'message_id': raw.get('message_id'),
            'message_seq': raw.get('message_seq'),
            'real_id': raw.get('real_id'),
            'real_seq': raw.get('real_seq'),
            'message_type': raw.get('message_type'),
            'sender': raw.get('sender'),
            'raw_message': 文本,
            'font': raw.get('font'),
            'sub_type': raw.get('sub_type'),
            'message': [{'type': 'text', 'data': {'text': 文本}}],
            'message_format': raw.get('message_format'),
            'post_type': raw.get('post_type'),
            'target_id': raw.get('target_id'),
        }