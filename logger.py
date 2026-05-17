from astrbot.api import logger
info日志 = 0  #info便于调试，不与其他插件debug混乱在一起
if info日志:
    debug = logger.info
else:
    debug = logger.debug

info = logger.info

warning = logger.warning

error = logger.error

critical = logger.critical

__all__ = ["debug", "info", "warning", "error", "critical"]