"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
import platform
from pathlib import Path

# 版本信息
YEAR = 2026
VERSION = "3.2.3"
ABOUT_URL = "https://github.com/123panNextGen/123pan"

# 日志保留天数
LOG_RETENTION_DAYS = 7

# 配置文件目录
if platform.system() == "Windows":
    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "123pan"
else:
    CONFIG_DIR = Path.home() / ".config" / "123pan"

# 设备伪装数据
from ..data.devices import all_device_type, all_os_versions  # noqa: E402, F401
