"""
应用常量定义
"""

import json
from pathlib import Path

# 版本信息
YEAR = 2026
VERSION = "3.1.1"
ABOUT_URL = "https://github.com/123panNextGen/123pan"

# 日志保留天数
LOG_RETENTION_DAYS = 7

# 云盘最大容量（字节）默认 2TB
MAX_STORAGE_CAPACITY = 2 * 1024 * 1024 * 1024 * 1024  # 2TB

# 设备伪装数据（从 JSON 文件加载）
_data_file = Path(__file__).resolve().parent.parent / "data" / "devices.json"
with open(_data_file, "r", encoding="utf-8") as _f:
    _device_data = json.load(_f)
all_device_type: list[str] = _device_data["all_device_type"]
all_os_versions: list[str] = _device_data["all_os_versions"]
del _data_file, _f, _device_data
