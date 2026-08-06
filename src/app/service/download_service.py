"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
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

    def download_from_url(self, url, file_name, download_path="download"):
        """从URL下载文件（简单单线程）。"""
        download_dir = Path(download_path)
        if not download_dir.exists():
            logger.info("创建下载目录")
            download_dir.mkdir(parents=True, exist_ok=True)

        file_path = download_dir / file_name
        temp_path = file_path.with_suffix(file_path.suffix + ".123pan")

        if temp_path.exists():
            temp_path.unlink()

        # 检测 JSON 重定向：CDN 可能返回 redirect_url 而非文件内容
        redirect_count = 0
        while redirect_count < 3:
            resp = self._session.transfer.get(url, stream=True, timeout=10)
            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type:
                break
            body = resp.json()
            data = body.get("data") or {}
            redirect_url = data.get("RedirectUrl", data.get("redirect_url", ""))
            if redirect_url and redirect_url.startswith("http"):
                logger.info("下载遇到 JSON 重定向: %s ...", redirect_url[:80])
                url = redirect_url
                redirect_count += 1
                continue
            # JSON 但不是有效重定向，视为错误
            msg = body.get("message", body.get("msg", "未知错误"))
            logger.error("CDN 返回 JSON 错误: %s", body)
            raise RuntimeError(f"下载 {file_name} 失败，CDN 返回: {msg}")

        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        os.rename(temp_path, file_path)

    def set_multi_thread(self, enabled: bool):
        """启用或禁用多线程下载。"""
        self._session.set_multi_thread(enabled)

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


