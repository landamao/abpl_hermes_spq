import os, json, yaml, random, aiohttp
from aiocqhttp import ActionFailed
from astrbot.api.all import AstrBotConfig, BaseMessageComponent, MessageChain, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from .logger import logger
from .message_id import MessageId
from .status import Status


class NapCatSend:
    """所有NapCat统一请求模块"""

    def __init__(self, config:AstrBotConfig):
        self.config = config
        self.event:AiocqhttpMessageEvent|None = None
        连接配置: dict = config['连接配置']
        self.消息发送方式: str = 连接配置['消息发送方式'].strip()
        if self.消息发送方式 == "NapCat Http 服务器":
            self.NapCat_api_url: str = 连接配置['NapCat_api_url'].strip().rstrip('/')
            self.NapCat_api_token: str = 连接配置['NapCat_api_token'].strip()
            # aiohttp.ClientSession 需要在异步上下文中创建
            self.http会话 = None
            self._http_headers = {}
            if self.NapCat_api_token:
                self._http_headers["Authorization"] = f"Bearer {self.NapCat_api_token}"
        else:
            self.NapCat_api_url: str = ""
            self.NapCat_api_token: str = ""
            self.http会话 = None
        # ========== emoji配置 ==========
        emoji配置: dict = config['emoji配置']
        self.回复消息贴表情: bool = emoji配置['回复消息贴表情']
        贴表情列表: str = emoji配置['贴表情列表'].strip()  # 字符串类型，逗号分隔
        if not 贴表情列表:
            config['emoji配置']['贴表情列表'] = config.schema['emoji配置']['items']['贴表情列表']['default']
            logger.warning("[Hermes适配器] 贴表情列表为空，已恢复默认")
            贴表情列表: str = emoji配置['贴表情列表'].strip()
        try:
            清理后 = (贴表情列表.replace('\n', '').replace('\r', '')
                    .replace(' ', '').replace('\t', '').replace('，', ','))
            parts = [i for i in 清理后.split(',') if i]
            self.贴表情列表: tuple = tuple(map(int, parts))
            规范后 = '，'.join(map(str, self.贴表情列表))
            if emoji配置['贴表情列表'] != 规范后:
                config['emoji配置']['贴表情列表'] = 规范后
                config.save_config()
        except Exception as e:
            贴表情列表 = config.schema['emoji配置']['items']['贴表情列表']['default']
            清理后 = (贴表情列表.replace('\n', '').replace('\r', '')
                    .replace(' ', '').replace('\t', '').replace('，', ','))
            parts = [i for i in 清理后.split(',') if i]
            self.贴表情列表: tuple = tuple(map(int, parts))
            logger.error(
                f"[Hermes适配器] 解析 emoji ID 配置失败，已自动使用默认ID列表：{'，'.join(map(str, self.贴表情列表))}\n{e}",
                exc_info=True)

        # ========== 脱敏配置 ==========
        脱敏配置: dict = config['脱敏配置']
        self.敏感字符列表: list[str] = 脱敏配置['敏感字符列表']
        self.替换目标: str = 脱敏配置['替换目标']
        自动添加密钥: bool = 脱敏配置['自动添加密钥']
        self.Hermes配置文件路径 = 脱敏配置['Hermes配置文件路径']

        if 自动添加密钥:
            self._加载api密钥()
            self._加载Hermes配置()
            self.config['脱敏配置']['敏感字符列表'] = [str(i).strip() for i in self.敏感字符列表 if str(i).strip()]
            self.敏感字符列表 = self.config['脱敏配置']['敏感字符列表']
        self.自动艾特用户 = config['授权配置']['自动艾特用户'].strip()

        try:
            self.自动艾特用户 = int(self.自动艾特用户) if self.自动艾特用户 else 0
        except (TypeError, ValueError):
            logger.error("[Hermes适配器] 自动艾特用户请填写整数qq号")
            self.自动艾特用户 = False
        self.触发艾特关键词:list = config['授权配置']['触发艾特关键词']
        if not self.触发艾特关键词:
            config['授权配置']['触发艾特关键词'] = self.触发艾特关键词 = config.schema['授权配置']['items']['触发艾特关键词']['default']

        if "*" in self.触发艾特关键词:
            self.触发艾特关键词 = ["*"] # 先设置好，避免无意义遍历判断

        logger.info(f"自动艾特用户：{self.自动艾特用户}")
        logger.info(f"触发关键词：{self.触发艾特关键词}")

    def set_event(self, event:AiocqhttpMessageEvent) -> None:
        """设置event"""
        self.event = event

    async def 贴表情(self, mid: str|int|dict) -> dict:
        """给消息贴表情回应"""
        原mid = mid
        if isinstance(mid, dict):
            if 'message_id' in mid:
                mid = mid['message_id']
            elif 'data' in mid:
                mid = mid['data'].get('message_id')
        elif isinstance(mid, (int, str)):
            mid = str(mid)
        if not mid:
            logger.warning(f"[Hermes适配器] 贴表情未找到有效消息ID：{原mid}")
            return {}
        动作 = "set_msg_emoji_like"
        参数 = {
            "message_id": str(mid),
            "emoji_id": random.choice(self.贴表情列表),
            "set": True
        }
        结果 = await self.发送动作参数到NapCat(动作, 参数)
        if 结果.get('status') == 'ok' or 结果.get('retcode') == 0:
            Status.贴表情成功 += 1
        else:
            Status.贴表情失败 += 1
        logger.debug(f"[Hermes适配器] 贴表情发送结果：{结果}")
        return 结果

    async def 戳一戳(self, qq: str | int) -> dict:
        if not qq:
            logger.warning(f"[Hermes适配器] （戳一戳）qq号不是有效值{qq}")
            return {}
        return await self.发送动作参数到NapCat("send_poke", {"user_id": str(qq)})

    async def 发送框架消息链到NapCat(self, 消息链:list[BaseMessageComponent]|MessageChain, 类型:str, ID:str, echo=None) -> dict:
        """发送框架类型的消息链到NapCat
        Args:
            消息链(list[BaseMessageComponent]|MessageChain): 框架消息链
            类型(str): 私聊or群聊
            ID(str)：私聊qq号或群号
        Returns:
            发送结果"""
        # 过滤不兼容的嵌套 Reply 组件
        原消息链 = 消息链
        if isinstance(消息链, MessageChain):
            原消息链 = 消息链.chain
        新消息链 = [c for c in 原消息链 if not isinstance(c, Reply)]
        消息组 = await self.event._parse_onebot_json(MessageChain(chain=新消息链))
        # 重新插入干净的 Reply
        if 原消息链 and isinstance(原消息链[0], Reply):
            消息组.insert(0, {"type": "reply", "data": {"id": str(原消息链[0].id)}})

        参数 = {'message': 消息组}

        if 类型 == "私聊":
            参数['user_id'] = ID
            动作 = "send_private_msg"
        elif 类型 == "群聊":
            动作 = "send_group_msg"
            参数['group_id'] = ID
        else:
            return {"echo": echo, "status": "failed", "retcode": -1, "data": None}
        return await self.发送data消息到NapCat({"action": 动作, "params": 参数, "echo": echo})

    async def 发送动作参数到NapCat(self, 动作:str, 参数:dict, echo=None) -> dict:
        """发送动作参数到NapCat"""
        return await self.发送data消息到NapCat({"action": 动作, "params": 参数, "echo": echo})

    async def 发送data消息到NapCat(self, data:dict) -> dict:
        """所有发送消息到NapCat统一接口"""
        data = self.数据文本脱敏(data)
        data = self.自动艾特(data)
        if self.消息发送方式 == "框架已有的WebSocket":
            结果 = await self._通过框架发送消息到NapCat(data)
        elif self.消息发送方式 == "NapCat Http 服务器":
            结果 = await self._通过HTTP发送消息到NapCat(data)
        else:
            logger.critical(f"意外未知的消息发送方式：{self.消息发送方式}\n原数据：{str(data)}")
            结果 = await self._通过框架发送消息到NapCat(data)
        return 结果

    def _加载api密钥(self):
        """从 AstrBot cmd_config.json 自动加载 API 密钥到敏感字符列表"""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.dirname(os.path.dirname(script_dir))
            cmd_config_path = os.path.join(data_dir, 'cmd_config.json')
            with open(cmd_config_path, 'r', encoding='utf-8-sig') as f:
                cmd_config = json.load(f)
            for source in cmd_config.get('provider_sources', []):
                keys = source.get('key', [])
                if isinstance(keys, str):
                    keys = [keys]
                self.敏感字符列表.extend(keys)
            self.敏感字符列表 = list(dict.fromkeys(self.敏感字符列表))
            self.config['脱敏配置']['敏感字符列表'] = self.敏感字符列表
            logger.info(f"[Hermes适配器] 已从配置文件自动加载 {len(self.敏感字符列表)} 个密钥字符")
        except Exception as e:
            logger.warning(f"[Hermes适配器] 自动读取 AstrBot 密钥失败: {e}")

    def _加载Hermes配置(self):
        """读取 Hermes config.yaml，提取所有 api_key 并加入敏感字符列表"""

        def _递归提取api_key(data):
            """递归提取数据中所有的 api_key 字段值"""
            keys = []
            if isinstance(data, dict):
                for k, v in data.items():
                    if k == "api_key":
                        keys.append(v)
                    keys.extend(_递归提取api_key(v))
            elif isinstance(data, list):
                for item in data:
                    keys.extend(_递归提取api_key(item))
            return keys

        try:
            if not os.path.exists(self.Hermes配置文件路径):
                logger.warning(f"[Hermes适配器] Hermes 配置文件不存在: {self.Hermes配置文件路径}")
                return
            with open(self.Hermes配置文件路径, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            if config_data is None:
                return
            hermes_keys = _递归提取api_key(config_data)
            if hermes_keys:
                # 合并到敏感字符列表并去重
                self.敏感字符列表.extend(hermes_keys)
                self.敏感字符列表 = list(dict.fromkeys(self.敏感字符列表))
                self.config['脱敏配置']['敏感字符列表'] = self.敏感字符列表
                logger.info(f"[Hermes适配器] 从 Hermes 配置中提取到 {len(hermes_keys)} 个 API Key，已加入敏感字符列表")
            else:
                logger.info("[Hermes适配器] Hermes 配置中未找到任何 api_key 字段")
        except yaml.YAMLError as e:
            logger.error(f"[Hermes适配器] 解析 YAML 失败: {e}")
        except Exception as e:
            logger.error(f"[Hermes适配器] 读取 Hermes 配置失败: {e}")

    async def _通过框架发送消息到NapCat(self, data:dict) -> dict:
        """<说明>"""
        action = data.get('action', '')
        params = data.get('params', {})
        echo = data.get('echo')
        logger.debug("[Hermes适配器] 通过框架方法发送到NapCat")
        if self.event is None:
            logger.warning(f"[Hermes适配器] event 为 None，无法通过框架发送。请先在群/私聊发送任意消息激活。原数据：{data}")
            return {"echo": echo, "status": "failed", "retcode": -1, "data": None, "msg": "event 未初始化，请先发送任意消息激活"}
        try:
            结果 = await self.event.bot.call_action(action, **params)
            返回 = {"echo": echo, "status": "ok", "retcode": 0, "data": 结果 or {}}
            if action in ("set_msg_emoji_like", "send_poke"):
                return 返回
            MessageId.add(结果)
            if self.回复消息贴表情:
                await self.贴表情(结果)
            Status.NapCat发送成功 += 1
        except ActionFailed as e:
            Status.NapCat发送失败 += 1
            logger.error(f"[Hermes适配器] 转发消息到NapCat失败\n原数据：{data}\n错误信息：{e}", exc_info=True)
            结果 = e.__dict__.get('result')
            结果['echo'] = echo
            返回 = 结果
        except Exception as e:
            Status.NapCat发送失败 += 1
            logger.error(f"[Hermes适配器] 转发消息到NapCat失败\n原数据：{data}\n错误信息：{e}", exc_info=True)
            返回 = {"echo": echo, "status": "failed", "retcode": -1, "data": None, "msg": str(e)}
        return 返回

    async def _通过HTTP发送消息到NapCat(self, data: dict) -> dict:
        """通过 HTTP 会话转发 Hermes 消息到 NapCat"""
        action = data.get('action', '')
        params = data.get('params', {})
        echo = data.get('echo')
        logger.debug("[Hermes适配器] 通过HTTP发送到NapCat")

        if self.http会话 is None or self.http会话.closed:
            self.http会话 = aiohttp.ClientSession(headers=self._http_headers)

        try:
            url = self.NapCat_api_url + '/' + action
            async with self.http会话.post(url, json=params) as resp:
                结果 = await resp.json()
            logger.debug(f"[Hermes适配器] API 响应: {action} -> {结果}")
            结果['echo'] = echo
            if action in ("set_msg_emoji_like", "send_poke"):
                return 结果
            MessageId.add(结果)
            if self.回复消息贴表情:
                await self.贴表情(结果)
            Status.NapCat发送成功 += 1
            return 结果

        except Exception as e:
            Status.NapCat发送失败 += 1
            logger.error(f"[Hermes适配器] API 调用失败\n原数据：{data}\n错误信息：{e}", exc_info=True)
            return {"echo": echo, "status": "failed", "retcode": 100, "msg": str(e), "data": None}

    def 自动艾特(self, data: dict) -> dict:
        """将数据增加自动艾特"""
        if not self.自动艾特用户:  # 单个int qq号
            return data
        if not ( "action" in data and "params" in data) :
            return data
        action = data['action']
        params = data['params']
        if action not in ("send_group_msg", "send_msg"):
            return data
        # 仅在群聊中启用自动艾特（私聊通常不需要）
        if action == "send_msg":
            if not params.get('group_id'):
                return data
        消息组 = params.get('message')
        if not 消息组:
            return data

        # 检查消息中是否包含触发关键词
        包含关键词 = False
        if self.触发艾特关键词[0] == "*":
            包含关键词 = True
        else:
            if isinstance(消息组, str):
                if any( i in 消息组 for i in self.触发艾特关键词 ):
                    包含关键词 = True
            elif isinstance(消息组, list):
                for 组件 in 消息组:
                    if 组件.get('type') == 'text':
                        text = 组件.get('data', {}).get('text', '')
                        if any( i in text for i in self.触发艾特关键词 ):
                            包含关键词 = True
                            break
        if not 包含关键词:
            return data

        # 构造艾特消息段
        艾特段 = {"type": "at", "data": {"qq": self.自动艾特用户}}

        # 修改 message
        if isinstance(消息组, str):
            new_message = [艾特段, {"type": "text", "data": {"text": 消息组}}]
        else:  # list
            new_message = [艾特段] + 消息组
        params['message'] = new_message

        # 同步更新 raw_message（添加CQ码格式的艾特）
        raw_message = params.get('raw_message')
        if raw_message is not None:
            at_cq = f"[CQ:at,qq={self.自动艾特用户}]"
            params['raw_message'] = at_cq + raw_message

        logger.debug(f"[Hermes适配器] 自动艾特：在消息中添加@用户{self.自动艾特用户}")

        return data


    def 数据文本脱敏(self, data:dict) -> dict:
        """对data中的文本进行脱敏，替换敏感字符"""
        if not self.敏感字符列表:
            return data

        if "params"not in data:
            return data
        params = data['params']
        message = params.get('message')
        if message is None:
            return data

        替换前 = str(message)

        if isinstance(message, str):
            for 敏感词 in self.敏感字符列表:
                if 敏感词 in message:
                    message = message.replace(敏感词, self.替换目标)
                    Status.脱敏替换次数 += 1
                    logger.debug(f"[Hermes适配器] 脱敏：替换字符串中的敏感字符")
            params['message'] = message

        elif isinstance(message, list):
            for segment in message:
                if segment.get('type') == 'text':
                    text = segment.get('data', {}).get('text', '')
                    for 敏感词 in self.敏感字符列表:
                        if 敏感词 in text:
                            text = text.replace(敏感词, self.替换目标)
                            Status.脱敏替换次数 += 1
                    segment['data']['text'] = text

        # 同步更新 raw_message
        if 替换前 != str(message):
            params['raw_message'] = params.get('raw_message', 替换前)
            for 敏感词 in self.敏感字符列表:
                if 敏感词 in params['raw_message']:
                    params['raw_message'] = params['raw_message'].replace(敏感词, self.替换目标)
            logger.debug(f"[Hermes适配器] 脱敏：已过滤消息中的敏感字符")

        return data