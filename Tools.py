"""不依赖其他参数的静态方法"""

授权命令映射 = {
    "/同意": "/approve",
    "/允许": "/approve",
    "/一直同意": "/approve always",
    "/一直允许": "/approve always",
    "/会话同意": "/approve session",
    "/会话允许": "/approve session",
    "/拒绝": "/deny",
    "/状态": "/status"
}


def 用户名(raw: dict) -> str:
    """
    从消息数据中提取发送者的显示名称。
    优先使用群名片（card），若为空或不存在则使用昵称（nickname）。
    """
    sender = raw.get('sender', {})
    card = sender.get('card', '')
    nickname = sender.get('nickname', '')
    return card or nickname

def 纯文本(raw: dict) -> str:
    text = ''
    messages = raw.get('message')
    if isinstance(messages, list):
        for i in messages:
            if i.get('type') == 'text':
                text += ' ' + str(i.get('data', {}).get('text', ''))
        return text.strip()
    else:
        return messages or ''

def 引用ID(raw: dict) -> str|None:
    """
    从消息数据中提取回复的消息 ID。
    如果存在回复（type 为 'reply'），返回其 data.id；否则返回 None。
    """
    message_list = raw.get('message', [])
    message_id = None
    for segment in message_list:
        if segment.get('type') == 'reply':
            # 回复的 id 可能为字符串或数字，统一转为字符串返回
            message_id = segment.get('data', {}).get('id')
    if message_id:
        return message_id
    return None

def 艾特ID(raw: dict) -> list[str]:
    """
    从消息数据中提取所有艾特（type 为 'at'）的 QQ 号。
    返回 QQ 号字符串列表，可能包含 'all'（全体成员）。
    如果没有艾特，返回空列表。
    """
    message_list = raw.get('message', [])
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


def 构造文本NapCat事件体(event, 文本: str, **kwargs) -> dict:
    """构造包含指定文本的NapCat事件体"""
    raw: dict = event.message_obj.raw_message
    基础字段 = {
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
    }
    if raw.get('group_id'):
        基础字段['group_id'] = raw.get('group_id')
        基础字段['group_name'] = raw.get('group_name')
    else:
        基础字段['target_id'] = raw.get('target_id')

    if kwargs:
        for key, value in kwargs.items():
            基础字段[key] = value
    return 基础字段

def 去除关键词(raw:dict, 关键词:str, 模式:str='in') -> dict:
    """
    Args:
        raw: 原始NapCat事件体
        关键词: 需要去除的关键词
        模式: s,e,in去除模式
    """
    message:dict|str = raw.get('message')
    raw_message:str = raw.get('raw_message', '').strip()
    if 模式 == 's':
        if isinstance(message, str):
            raw['message'] = message.strip()[len(关键词):]
        else:
            for i in message:
                if i.get('type') == 'text':
                    i['data']['text'] = i['data']['text'][len(关键词):]  #标准结果理论上可以直接[]访问
                    break
        if raw_message.startswith('[CQ:'):
            for i, j in enumerate(raw_message):
                if j == ']' and not raw_message[i + 1:].strip().startswith('[CQ:'):
                    start_str = raw_message[:i + 1].strip()
                    end_str = raw_message[i + 1:].strip()
                    处理后 = start_str + end_str[len(关键词):]
                    break
            else:
                处理后 = raw_message[len(关键词):]
        else:
            处理后 = raw_message[len(关键词):]
        raw['raw_message'] = 处理后
    elif 模式 == 'e':
        if isinstance(message, str):
            raw['message'] = message.strip()[:len(message)-len(关键词)]
        else:
            data = {}
            for i in message:
                if i.get('type') == 'text':
                    data = i.get('data')
                    continue
            if data:
                text = data['text']
                data['text'] = text[:len(text)-len(关键词)]

        if raw_message.endswith(关键词):
            处理后 = raw_message[:len(raw_message) - len(关键词)]
        else:
            index = 0
            for i, j in enumerate(raw_message):
                if raw_message[i:i + 4] == '[CQ:':
                    index = i
            if index:
                start_str = raw_message[:index].strip()
                end_str = raw_message[index:].strip()
                处理后 = start_str[:len(start_str) - len(关键词)] + end_str
            else:
                处理后 = raw_message[:len(raw_message) - len(关键词)]
        raw['raw_message'] = 处理后
    else:
        if isinstance(message, str):
            raw['message'] = message.replace(关键词, '', 1)
        else:
            for i in message:
                if i.get('type') == 'text':
                    if 关键词 in (text := i['data']['text']):
                        i['data']['text'] = text.replace(关键词, '', 1)
                        break
        raw['raw_message'] = raw_message.replace(关键词, '', 1)
    return raw