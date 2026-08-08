"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import threading
from pathlib import Path
from typing import Optional, Callable

from ..common.log import get_logger
from ..common.speed_limiter import SpeedLimiter

logger = get_logger(__name__)


class DownloadService:
    """下载服务。

    负责获取下载链接和执行下载（单线程/多线程）。
    """

    def __init__(self, session):
        self._session = session

    def link_by_fileDetail(self, file_detail, showlink=True):
        """按文件详情获取下载链接。

        Returns:
            str: 下载URL（成功）
            int: 错误码（失败）
        """
        result = self._session.get_file_link(file_detail)
        if result.code != 0:
            logger.error("获取下载链接失败，返回码: %s", result.code)
            logger.error(result.msg)
            return result.code
        redirect_url = result.data
        if showlink:
            logger.info("获取下载链接成功: %s", redirect_url)
        return redirect_url

    def set_multi_thread(self, enabled: bool, num_threads: int = 4):
        """启用或禁用多线程下载。

        Args:
            enabled: 是否启用多线程分片下载。
            num_threads: 每个文件的分片线程数。
        """
        self._session.set_multi_thread(enabled, num_threads)

    def set_download_speed_limit(self, kbps: int):
        """设置下载速度限制（KB/s），0 为不限速。"""
        if kbps > 0:
            self._session.set_speed_limiter(SpeedLimiter(kbps), is_upload=False)
        else:
            self._session.set_speed_limiter(None, is_upload=False)

    def set_proxy(self, proxy_type: str, host: str, port: int, username: str = "", password: str = ""):
        """设置下载代理。"""
        self._session.set_proxy_auth(proxy_type, host, port, username, password)

    def clear_proxy(self):
        """清除下载代理。"""
        self._session.set_proxy("")

    def download_file(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        resume_offset: int = 0,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """多线程分片下载文件（支持断点续传）。

        Args:
            cancel_event: 取消事件，置位时中止下载并返回 False（保留临时文件）。
        """
        return self._session.download_file_multithread(
            url, file_path, file_size, progress_callback, resume_offset, cancel_event
        )


