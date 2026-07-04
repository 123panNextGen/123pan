import logging
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from .const import LOG_RETENTION_DAYS

# 配置文件路径
if platform.system() == "Windows":
    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "123pan"
else:
    CONFIG_DIR = Path.home() / ".config" / "123pan"
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
        except ValueError, OSError:
            pass


def get_logger(name: str = "123pan"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

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


def open_log_file():
    if platform.system() == "Windows":
        os.startfile(LOG_FILE)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", LOG_FILE])
    else:
        subprocess.Popen(["xdg-open", LOG_FILE])


_cleanup_old_logs()
