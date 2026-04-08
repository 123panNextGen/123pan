import logging
import os
import platform
from pathlib import Path

# 配置文件路径
if platform.system() == "Windows":
    CONFIG_DIR = Path(os.environ.get("APPDATA", "") or (Path.home() / "AppData" / "Roaming")) / "123pan-open"
elif platform.system() == "Darwin":
    CONFIG_DIR = Path.home() / "Library" / "Application Support" / "123pan-open"
else:
    CONFIG_DIR = Path.home() / ".config" / "123pan-open"
LOG_FILE = CONFIG_DIR / "123pan-open.log"


def get_logger(name: str = "123pan-open"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler
    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
