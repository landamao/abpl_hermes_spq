from astrbot.api import logger

debug = logger.debug

info = logger.info

warning = logger.warning

error = logger.error

critical = logger.critical

def 设置info日志(b:bool=False) -> None:
    global debug
    if b:
        debug = logger.info
    else:
        debug = logger.debug