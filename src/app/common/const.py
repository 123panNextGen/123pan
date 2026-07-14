"""
应用常量定义
"""

# 版本信息
YEAR = 2026
VERSION = "3.1.4"
ABOUT_URL = "https://github.com/123panNextGen/123pan"

# 日志保留天数
LOG_RETENTION_DAYS = 7

# 云盘最大容量（字节）默认 2TB
MAX_STORAGE_CAPACITY = 2 * 1024 * 1024 * 1024 * 1024  # 2TB

# 设备伪装数据
from ..data.devices import all_device_type, all_os_versions  # noqa: E402, F401
