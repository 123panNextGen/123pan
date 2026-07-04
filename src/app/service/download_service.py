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

        resp = self._session.transfer.get(url, stream=True, timeout=10)
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
    ) -> bool:
        """多线程分片下载文件。"""
        return self._session.download_file_multithread(url, file_path, file_size, progress_callback)


