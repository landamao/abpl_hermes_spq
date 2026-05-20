from astrbot.api import logger as her_logger

class logger:
    """动态修改日志级别， 避免调试时与大量debug混在一起"""
    debug = her_logger.debug

    info = her_logger.info

    warning = her_logger.warning

    error = her_logger.error

    critical = her_logger.critical

    @classmethod
    def 设置info日志(cls, 开启:bool=False) -> None:
        if 开启:
            cls.debug = her_logger.info
        else:
            cls.debug = her_logger.debug