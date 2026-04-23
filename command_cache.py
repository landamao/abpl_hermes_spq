"""
指令缓存模块

负责构建、查找、验证 AstrBot 指令处理器缓存。
"""
import copy
from typing import Dict, Optional, Tuple
from astrbot.api.all import logger
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata


# 指令分类关键词映射（全局共享，避免重复定义）
COMMAND_CATEGORY_MAP = {
    '音乐': ['点歌', 'play', '搜歌', 'song', 'meting', 'kugou', 'kuwo', 'netease', 'qqmusic', 'tencent', 'cloudmusic', '网易', '酷狗', '酷我', 'QQ', '腾讯'],
    '宠物': ['宠物', '领养', '喂食', '玩耍', '散步', '进化', '技能', '背包', '商店', '购买', '装备', '对决', '审判', '偷', '丢弃'],
    '好感度': ['好感', '查看好感', '查询好感', '设置好感', '重置好感', '好感排行', '负好感', '印象', '设置印象'],
    '群管理': ['群规', '添加群规', '删除群规', '设置群规', '群拉黑', '群解除拉黑', '屏蔽', '取消屏蔽', '拉黑', '解除拉黑', '黑名单'],
    '系统': ['状态', '系统状态', '运行状态', '模型', '当前模型', '切换模型', '重启', '更新', '备份', '恢复'],
    '生图': ['画图', '生图', '图片', '切换生图', '禁用生图', '启用生图', '特权生图'],
    '表情包': ['表情', 'meme', '表情包', '表情列表', '表情启用', '表情禁用'],
    '分析': ['群分析', '分析设置', '自然分析'],
    '其他': []
}


def build_command_cache(context) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """
    构建指令处理器缓存。

    Args:
        context: AstrBot Context 对象

    Returns:
        (处理器缓存字典, 别名到指令名映射)
    """
    处理器缓存: Dict[str, Dict] = {}
    别名到指令: Dict[str, str] = {}

    try:
        所有插件 = context.get_all_stars()
        所有插件 = [p for p in 所有插件 if p.activated]
    except Exception as e:
        logger.error(f"[HermesAdapter] 获取插件列表失败: {e}")
        return 处理器缓存, 别名到指令

    if not 所有插件:
        return 处理器缓存, 别名到指令

    跳过插件 = {"astrbot", "hermes_adapter"}

    # 构建模块路径到插件的映射
    模块映射插件 = {}
    for 插件实例 in 所有插件:
        插件名称 = getattr(插件实例, "name", "未知插件")
        模块路径 = getattr(插件实例, "module_path", None)
        if 插件名称 in 跳过插件 or not 模块路径:
            continue
        模块映射插件[模块路径] = (插件实例, 插件名称)

    for 处理器 in star_handlers_registry:
        if not isinstance(处理器, StarHandlerMetadata):
            continue

        插件信息 = 模块映射插件.get(处理器.handler_module_path)
        if not 插件信息:
            continue

        插件实例, 插件名称 = 插件信息

        指令名称 = None
        别名集合 = []
        指令描述 = 处理器.desc or "无描述"
        是否管理员指令 = False

        for 过滤器 in 处理器.event_filters:
            if isinstance(过滤器, CommandFilter):
                指令名称 = 过滤器.command_name
                if hasattr(过滤器, 'alias') and 过滤器.alias:
                    if isinstance(过滤器.alias, set):
                        别名集合 = list(过滤器.alias)
                    elif isinstance(过滤器.alias, list):
                        别名集合 = 过滤器.alias
            elif isinstance(过滤器, CommandGroupFilter):
                指令名称 = 过滤器.group_name
            elif isinstance(过滤器, PermissionTypeFilter):
                是否管理员指令 = True

        if 指令名称:
            if 指令名称.startswith("/"):
                指令名称 = 指令名称[1:]

            处理器信息 = {
                "command": 指令名称,
                "description": 指令描述,
                "plugin": 插件名称,
                "aliases": 别名集合,
                "is_admin": 是否管理员指令,
                "handler": 处理器,
                "module_path": 处理器.handler_module_path
            }

            处理器缓存[指令名称] = 处理器信息

            for 别名 in 别名集合:
                if 别名.startswith("/"):
                    别名 = 别名[1:]
                别名到指令[别名] = 指令名称

    logger.info(f"[HermesAdapter] 已缓存 {len(处理器缓存)} 个指令处理器")
    return 处理器缓存, 别名到指令


def build_all_commands_set(处理器缓存: Dict[str, Dict], 别名到指令: Dict[str, str]) -> set:
    """
    构建所有指令名 + 别名的集合（用于快速判断消息是否为框架指令）。

    Returns:
        包含所有指令名和别名的 set，元素全部为小写形式
    """
    指令集合 = set()
    for 指令名 in 处理器缓存:
        指令集合.add(指令名.lower())
    for 别名 in 别名到指令:
        指令集合.add(别名.lower())
    return 指令集合


def check_command_allowed(指令: str, 白名单: list, 黑名单: list) -> Tuple[bool, str]:
    """
    检查指令是否允许执行。

    Args:
        指令: 指令名称
        白名单: 指令白名单（为空则不限制）
        黑名单: 指令黑名单

    Returns:
        (是否允许, 原因)
    """
    if 指令.startswith('/'):
        指令 = 指令[1:]

    if 黑名单 and 指令 in 黑名单:
        return False, f'指令 {指令} 在黑名单中'

    if 白名单 and 指令 not in 白名单:
        return False, f'指令 {指令} 不在白名单中'

    return True, '可以执行'


def resolve_command(指令: str, 别名到指令: Dict[str, str], 处理器缓存: Dict[str, Dict]) -> Optional[Dict]:
    """
    通过指令名或别名查找处理器信息。

    Args:
        指令: 输入的指令名或别名
        别名到指令: 别名→指令名映射
        处理器缓存: 指令名→处理器信息映射

    Returns:
        处理器信息字典，未找到返回 None
    """
    if 指令.startswith('/'):
        指令 = 指令[1:]
    实际指令 = 别名到指令.get(指令, 指令)
    return 处理器缓存.get(实际指令)


def categorize_commands(处理器缓存: Dict[str, Dict], 分类过滤: str = "") -> Dict[str, list]:
    """
    将指令按分类整理。

    Args:
        处理器缓存: 指令处理器缓存
        分类过滤: 只返回指定分类（为空则返回全部）

    Returns:
        分类名 → 指令信息列表
    """
    分类字典: Dict[str, list] = {}

    for 指令名称, 处理器信息 in 处理器缓存.items():
        别名集合 = 处理器信息['aliases']
        指令描述 = 处理器信息['description']

        所属分类 = '其他'
        for 分类, 关键词 in COMMAND_CATEGORY_MAP.items():
            if any(kw in 指令名称 or kw in 指令描述 for kw in 关键词):
                所属分类 = 分类
                break
            for 别名 in 别名集合:
                if any(kw in 别名 for kw in 关键词):
                    所属分类 = 分类
                    break

        if 分类过滤 and 所属分类 != 分类过滤:
            continue

        if 所属分类 not in 分类字典:
            分类字典[所属分类] = []

        用法 = 指令名称
        if 别名集合:
            用法 = f"{指令名称} (别名: {', '.join(别名集合[:3])})"

        指令信息 = {
            'name': 指令名称,
            'description': 指令描述,
            'usage': 用法,
            'aliases': 别名集合,
            'plugin': 处理器信息['plugin'],
            'is_admin': 处理器信息['is_admin'],
            'category': 所属分类
        }

        分类字典[所属分类].append(指令信息)

    return 分类字典
