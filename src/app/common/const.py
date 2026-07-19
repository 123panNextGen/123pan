"""
应用常量定义
"""

import os
import platform
from pathlib import Path

# 版本信息
YEAR = 2026
VERSION = "3.2.1"
ABOUT_URL = "https://github.com/123panNextGen/123pan"

# 日志保留天数
LOG_RETENTION_DAYS = 7

# 云盘最大容量（字节）默认 2TB
MAX_STORAGE_CAPACITY = 2 * 1024 * 1024 * 1024 * 1024  # 2TB

# 配置文件目录
if platform.system() == "Windows":
    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "123pan"
else:
    CONFIG_DIR = Path.home() / ".config" / "123pan"

# 设备伪装数据
from ..data.devices import all_device_type, all_os_versions  # noqa: E402, F401
