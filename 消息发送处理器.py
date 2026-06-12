"""
消息处理器 — 配置 + 钩子一体化

管理 emoji/脱敏/艾特/授权 配置，并通过钩子自动处理发送消息。
"""
import os, json, yaml, random
from astrbot.api.all import AstrBotConfig
from .status import Status
from .logger import logger
from .message_id import MessageId

class 消息发送处理器:
    """消息处理器 — 配置管理 + 发送钩子"""

    def __init__(self, config: AstrBotConfig):
        self.config = config

        # ========== emoji配置 ==========
        emoji配置: dict = config['emoji配置']
        self.开启回复消息贴表情: bool = emoji配置['回复消息贴表情']
        贴表情列表: str = emoji配置['贴表情列表'].strip()
        if not 贴表情列表:
            config['emoji配置']['贴表情列表'] = config.schema['emoji配置']['items']['贴表情列表']['default']
            logger.warning("贴表情列表为空，已恢复默认")
            贴表情列表: str = emoji配置['贴表情列表'].strip()
        try:
            清理后 = ''.join(贴表情列表.split()).replace('，', ',')
            parts = [i for i in 清理后.split(',') if i]
            self.贴表情列表: tuple = tuple(map(int, parts))
            规范后 = '，'.join(map(str, self.贴表情列表))
            if emoji配置['贴表情列表'] != 规范后:
                config['emoji配置']['贴表情列表'] = 规范后
                config.save_config()
        except Exception as e:
            贴表情列表 = config.schema['emoji配置']['items']['贴表情列表']['default']
            清理后 = ''.join(贴表情列表.split()).replace('，', ',')
            parts = [i for i in 清理后.split(',') if i]
            self.贴表情列表: tuple = tuple(map(int, parts))
            logger.error(
                f"解析 emoji ID 配置失败，已自动使用默认ID列表：{'，'.join(map(str, self.贴表情列表))}\n{e}",
                exc_info=True)

        # ========== 脱敏配置 ==========
        脱敏配置: dict = config['脱敏配置']
        self.敏感字符列表: list[str] = 脱敏配置['敏感字符列表']
        self.替换目标: str = 脱敏配置['替换目标']
        自动添加密钥: bool = 脱敏配置['自动添加密钥']
        self.Hermes配置文件路径 = 脱敏配置['Hermes配置文件路径'].strip().strip('"\'')

        if 自动添加密钥:
            self._加载api密钥()
            self._加载Hermes配置()
            self.config['脱敏配置']['敏感字符列表'] = [str(i).strip() for i in self.敏感字符列表 if str(i).strip()]
            self.敏感字符列表 = self.config['脱敏配置']['敏感字符列表']

        # ========== 艾特/授权配置 ==========
        self.自动艾特用户 = config['授权配置']['自动艾特用户'].strip()
        try:
            self.自动艾特用户 = int(self.自动艾特用户) if self.自动艾特用户 else 0
        except (TypeError, ValueError):
            logger.error("自动艾特用户请填写整数qq号")
            self.自动艾特用户 = False
        self.触发艾特关键词: list = config['授权配置']['触发艾特关键词']
        if not self.触发艾特关键词:
            config['授权配置']['触发艾特关键词'] = self.触发艾特关键词 = config.schema['授权配置']['items']['触发艾特关键词']['default']

        if "*" in self.触发艾特关键词:
            self.触发艾特关键词 = ["*"]

        self.开启快速授权 = config['授权配置']['开启快速授权']
        if self.开启快速授权:
            self.触发授权关键词 = config['授权配置']['触发授权关键词']
            if not self.触发授权关键词:
                config['授权配置']['触发授权关键词'] = self.触发授权关键词 = config.schema['授权配置']['items']['触发授权关键词']['default']
        else:
            self.触发授权关键词 = []
        self.触发授权关键词 = [i.lower() for i in self.触发授权关键词]
        self.触发艾特关键词 = [i.lower() for i in self.触发艾特关键词]
        logger.info(f"自动艾特用户：{self.自动艾特用户}")
        logger.info(f"触发关键词：{self.触发艾特关键词}")

        # ========== 注册钩子 ==========
        from .napcat_send import 消息钩子
        消息钩子.发送前(self.数据脱敏, 优先级=90)
        消息钩子.发送前(self.自动艾特, 优先级=80)
        消息钩子.发送前(self.授权检查, 优先级=70)
        消息钩子.发送后(self.回复消息贴表情, 优先级=90)
        消息钩子.发送后(self.授权记录, 优先级=100)
        logger.info("处理器钩子已注册")

    # ========== 便捷方法 ==========

    def 随机表情(self) -> int:
        """从表情列表中随机选一个"""
        return random.choice(self.贴表情列表)

    # ========== 发送前钩子 ==========

    async def 数据脱敏(self, 事件, _):
        """对消息文本进行脱敏处理"""
        if not self.敏感字符列表:
            return
        params = 事件.参数
        message = params.get('message')
        if message is None:
            return
        替换目标 = self.替换目标
        if isinstance(message, str):
            for 敏感词 in self.敏感字符列表:
                if 敏感词 in message:
                    message = message.replace(敏感词, 替换目标)
                    Status.脱敏替换次数 += 1
            params['message'] = message
        elif isinstance(message, list):
            for segment in message:
                if segment.get('type') == 'text':
                    text = segment.get('data', {}).get('text', '')
                    for 敏感词 in self.敏感字符列表:
                        if 敏感词 in text:
                            text = text.replace(敏感词, 替换目标)
                            Status.脱敏替换次数 += 1
                    segment['data']['text'] = text

    async def 自动艾特(self, 事件, _):
        """根据关键词自动在消息前添加艾特"""
        if not 事件.是否群聊:
            return
        params = 事件.参数
        群号 = params.get('group_id')
        if not 群号 or not self.自动艾特用户:
            return
        消息组 = params.get('message')
        if not 消息组:
            return
        需要艾特 = False
        if self.触发艾特关键词[0] == "*":
            需要艾特 = True
        elif isinstance(消息组, str):
            需要艾特 = any(kw in 消息组.lower() for kw in self.触发艾特关键词)
        elif isinstance(消息组, list):
            for 组件 in 消息组:
                if 组件.get('type') == 'text':
                    text = 组件.get('data', {}).get('text', '').lower()
                    if any(kw in text for kw in self.触发艾特关键词):
                        需要艾特 = True
                        break
        if not 需要艾特:
            return
        if isinstance(消息组, str):
            params['message'] = f"[CQ:at,qq={self.自动艾特用户}]" + 消息组
        else:
            消息组.insert(0, {"type": "at", "data": {"qq": self.自动艾特用户}})

    async def 授权检查(self, 事件, _):
        """检查是否需要授权，标记到事件上供发送后处理"""
        if not 事件.是否群聊 or not self.开启快速授权:
            return
        params = 事件.参数
        消息组 = params.get('message')
        if not 消息组:
            return
        需要授权 = False
        if isinstance(消息组, str):
            需要授权 = any(kw in 消息组.lower() for kw in self.触发授权关键词)
        elif isinstance(消息组, list):
            for 组件 in 消息组:
                if 组件.get('type') == 'text':
                    text = 组件.get('data', {}).get('text', '').lower()
                    if any(kw in text for kw in self.触发授权关键词):
                        需要授权 = True
                        break
        if 需要授权:
            事件.设置额外信息("需要授权", True)

    # ========== 发送后钩子 ==========

    async def 回复消息贴表情(self, 事件, context):
        """发送成功后自动给消息贴表情"""
        if not self.开启回复消息贴表情:
            return
        if not 事件.结果 or 事件.结果.get('status') == 'failed':
            return
        动作 = 事件.动作
        if 动作 in ("set_msg_emoji_like", "send_poke"):
            return
        await context.贴表情(事件.结果, self.随机表情())

    async def 授权记录(self, 事件, _):
        """发送后记录授权信息"""
        if not 事件.获取额外信息("需要授权"):
            return
        群号 = 事件.群号
        qq = 事件.QQ号
        MessageId.add_sq(事件.结果, 群号 or qq)

    # ========== 私有方法：加载密钥 ==========

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
            logger.info(f"已从配置文件自动加载 {len(self.敏感字符列表)} 个密钥字符")
        except Exception as e:
            logger.warning(f"自动读取 AstrBot 密钥失败: {e}")

    def _加载Hermes配置(self):
        """读取 Hermes config.yaml，提取所有 api_key 并加入敏感字符列表"""

        def _递归提取api_key(data):
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
                logger.warning(f"Hermes 配置文件不存在: {self.Hermes配置文件路径}")
                return
            with open(self.Hermes配置文件路径, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            if config_data is None:
                return
            hermes_keys = _递归提取api_key(config_data)
            if hermes_keys:
                self.敏感字符列表.extend(hermes_keys)
                self.敏感字符列表 = list(dict.fromkeys(self.敏感字符列表))
                self.config['脱敏配置']['敏感字符列表'] = self.敏感字符列表
                logger.info(f"从 Hermes 配置中提取到 {len(hermes_keys)} 个 API Key，已加入敏感字符列表")
            else:
                logger.info("Hermes 配置中未找到任何 api_key 字段")
        except yaml.YAMLError as e:
            logger.error(f"解析 YAML 失败: {e}")
        except Exception as e:
            logger.error(f"读取 Hermes 配置失败: {e}")