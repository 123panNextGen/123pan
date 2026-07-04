import os
from pathlib import Path

from ..common.log import get_logger

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


