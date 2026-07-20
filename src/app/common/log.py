import logging
import os
import subprocess
from datetime import datetime

from .const import CONFIG_DIR, LOG_RETENTION_DAYS
LOG_DIR = CONFIG_DIR / "logs"
_LOG_TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = LOG_DIR / f"log_{_LOG_TIMESTAMP}.log"


def _cleanup_old_logs():
    """删除超过保留天数的旧日志文件，仅保留最近 LOG_RETENTION_DAYS 天。"""
    if not LOG_DIR.exists():
        return
    cutoff = datetime.now().timestamp() - LOG_RETENTION_DAYS * 86400
    for f in LOG_DIR.glob("log_*.log"):
        try:
            ts_str = f.stem[4:]  # 去掉 "log_" 前缀
            file_time = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
            if file_time.timestamp() < cutoff:
                f.unlink()
        except (ValueError, OSError):
            pass


_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_LEVEL_NAMES = list(_LEVEL_MAP.keys())

_current_level = logging.DEBUG


def get_logger(name: str = "123pan"):
    logger = logging.getLogger(name)
    logger.setLevel(_current_level)

    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        if not LOG_DIR.exists():
            LOG_DIR.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def set_log_level(level_name_or_int):
    """动态调整日志等级。

    Args:
        level_name_or_int: 字符串（"DEBUG"/"INFO"/"WARNING"/"ERROR"/"CRITICAL"）
                          或 logging 等级常量（logging.DEBUG 等）。
    """
    global _current_level

    if isinstance(level_name_or_int, str):
        level = _LEVEL_MAP.get(level_name_or_int.upper())
        if level is None:
            logger = logging.getLogger("123pan")
            logger.warning("无效的日志等级: %s，使用 DEBUG", level_name_or_int)
            level = logging.DEBUG
    else:
        level = level_name_or_int

    _current_level = level

    root_logger = logging.getLogger("123pan")
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)


def get_current_level_name():
    """获取当前日志等级名称（字符串）。"""
    for name, val in _LEVEL_MAP.items():
        if val == _current_level:
            return name
    return "DEBUG"


def get_level_names():
    """获取所有可用的日志等级名称列表。"""
    return _LEVEL_NAMES.copy()


def open_log_file():
    if platform.system() == "Windows":
        os.startfile(LOG_FILE)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", LOG_FILE])
    else:
        subprocess.Popen(["xdg-open", LOG_FILE])


_cleanup_old_logs()
