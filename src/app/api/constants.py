"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

API 端点域名常量（session / session_file / download_url 共用，
独立成模块以避免循环导入）。
"""

# 主 API 域名
BASE_URL = "https://www.123pan.cn"
# 备用 API 域名（主域名连接失败时自动切换）
FALLBACK_BASE_URL = "https://api.123278.com"
# 二维码登录专用域名（web 端登录接口）
LOGIN_BASE_URL = "https://login.123pan.com"
# 离线下载专用域名（解析/提交任务，固定使用 api.123278.com）
OFFLINE_BASE_URL = "https://api.123278.com"

CLIENT_SIMULATION_HEADERS = {
	"platform": "android",
	"devicename": "Xiaomi",
	"app-version": "61",
	"x-app-version": "2.4.0",
}
CLIENT_SIMULATION_DYNAMIC_HEADERS = (
	"user-agent",
	"osversion",
	"devicetype",
)
