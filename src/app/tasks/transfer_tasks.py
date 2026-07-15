"""
传输任务和线程模块。

包含：
- TransferTask / UploadTask / DownloadTask: 数据传输任务模型
- UploadThread: 后台上传线程（支持速度限制、暂停/恢复）
- DownloadThread: 后台下载线程（支持多线程分片和速度限制、暂停/恢复）

从 view/transfer_interface.py 提取，以分离 UI 和业务逻辑。
"""

import threading
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..common.config import ConfigManager
from ..common.log import get_logger

logger = get_logger(__name__)


class TransferTask:
    """传输任务基类"""

    def __init__(self, file_name, file_size):
        self.file_name = file_name
        self.file_size = file_size
        self.progress = 0
        self.status = "等待中"


class UploadTask(TransferTask):
    """上传任务"""

    def __init__(self, file_name, file_size, local_path, target_dir_id):
        super().__init__(file_name, file_size)
        self.local_path = local_path
        self.target_dir_id = target_dir_id


class DownloadTask(TransferTask):
    """下载任务"""

    def __init__(self, file_name, file_size, file_id, save_path, current_dir_id=0):
        super().__init__(file_name, file_size)
        self.file_id = file_id
        self.save_path = save_path
        self.current_dir_id = current_dir_id


class UploadThread(QThread):
    """上传线程（支持速度限制、暂停/恢复）"""

    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task, pan):
        super().__init__()
        self.task = task
        self.pan = pan
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始状态：不暂停
        self._cancelled = False

    def pause(self):
        """暂停传输"""
        self._pause_event.clear()
        self.status_updated.emit("已暂停")

    def resume(self):
        """恢复传输"""
        self._pause_event.set()
        self.status_updated.emit("上传中")

    def cancel(self):
        """取消传输"""
        self._cancelled = True
        self._pause_event.set()  # 解除暂停以便退出

    def run(self):
        try:
            self._pause_event.wait()  # 检查是否立即暂停
            self.status_updated.emit("上传中")
            logger.info(
                "上传线程启动: %s (%.2f MB)",
                self.task.file_name,
                self.task.file_size / 1024 / 1024,
            )

            ul_limit = ConfigManager.get_setting("uploadSpeedLimit", 0)
            self.pan.set_upload_speed_limit(ul_limit)

            current_parent_id = self.pan.parent_file_id
            self.pan.parent_file_id = self.task.target_dir_id
            logger.debug("上传目标目录: %s", self.task.target_dir_id)

            t0 = time.monotonic()
            self.pan.up_load(self.task.local_path)
            elapsed = time.monotonic() - t0

            self.pan.parent_file_id = current_parent_id

            if self._cancelled:
                self.status_updated.emit("已取消")
                return

            self.progress_updated.emit(100)
            self.status_updated.emit("已完成")
            self.finished.emit()
            logger.info("上传完成: %s (%.1fs)", self.task.file_name, elapsed)
        except Exception as e:
            logger.error("上传失败: %s: %s", self.task.file_name, e)
            self.error.emit(str(e))
            self.status_updated.emit("失败")


class DownloadThread(QThread):
    """下载线程（支持多线程分片、速度限制、暂停/恢复）"""

    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task, pan):
        super().__init__()
        self.task = task
        self.pan = pan
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancelled = False

    def pause(self):
        """暂停传输"""
        self._pause_event.clear()
        self.status_updated.emit("已暂停")

    def resume(self):
        """恢复传输"""
        self._pause_event.set()
        self.status_updated.emit("下载中")

    def cancel(self):
        """取消传输"""
        self._cancelled = True
        self._pause_event.set()

    def run(self):
        try:
            self.status_updated.emit("下载中")
            logger.info(
                "下载线程启动: %s, file_id=%s, size=%.2f MB",
                self.task.file_name,
                self.task.file_id,
                self.task.file_size / 1024 / 1024,
            )

            multi_thread = ConfigManager.get_setting("multiThreadDownload", True)
            dl_limit = ConfigManager.get_setting("downloadSpeedLimit", 0)
            logger.debug(
                "下载配置: multi_thread=%s, speed_limit=%d KB/s",
                multi_thread,
                dl_limit,
            )

            self.pan.set_download_multi_thread(multi_thread)
            self.pan.set_download_speed_limit(dl_limit)

            def _on_progress(downloaded, total):
                if self._cancelled:
                    return
                self._pause_event.wait()  # 暂停时阻塞回调
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    self.progress_updated.emit(pct)

            target_file = self._find_file_info()
            if not target_file:
                target_file = {
                    "FileId": self.task.file_id,
                    "FileName": self.task.file_name,
                    "Type": 0,
                    "Size": self.task.file_size,
                    "Etag": "",
                    "S3KeyFlag": False,
                }
                logger.debug(
                    "未找到文件信息，使用构造数据: file_id=%s", self.task.file_id
                )
            else:
                real_size = int(target_file.get("Size", 0) or 0)
                if real_size > 0:
                    self.task.file_size = real_size
                logger.debug(
                    "已找到文件信息: name=%s, size=%s",
                    target_file.get("FileName"),
                    target_file.get("Size"),
                )

            download_url = self.pan.link_by_fileDetail(target_file, showlink=False)
            if isinstance(download_url, int):
                raise RuntimeError(f"获取下载链接失败，返回码: {download_url}")
            logger.debug("下载链接已获取")

            file_path = Path(self.task.save_path)
            save_dir = file_path.parent
            if not save_dir.exists():
                save_dir.mkdir(parents=True, exist_ok=True)
                logger.debug("创建下载目录: %s", save_dir)

            file_size = int(target_file.get("Size", self.task.file_size) or 0)
            t0 = time.monotonic()
            success = self.pan.download_file(
                download_url,
                file_path,
                file_size,
                progress_callback=_on_progress,
            )
            elapsed = time.monotonic() - t0

            if not success:
                raise RuntimeError("下载失败")

            if self._cancelled:
                self.status_updated.emit("已取消")
                return

            self.progress_updated.emit(100)
            self.status_updated.emit("已完成")
            self.finished.emit()
            speed = file_size / 1024 / 1024 / elapsed if elapsed > 0 else 0
            logger.info(
                "下载完成: %s (%.2f MB / %.1fs / %.1f MB/s)",
                self.task.file_name,
                file_size / 1024 / 1024,
                elapsed,
                speed,
            )
        except Exception as e:
            logger.error(
                "下载失败: %s: %s:%s",
                self.task.file_name,
                type(e).__name__,
                e,
            )
            self.error.emit(str(e))
            self.status_updated.emit("失败")

    def _find_file_info(self):
        """在多个数据源中查找文件信息。"""
        # 在当前目录中查找
        code, files = self.pan.get_dir_by_id(
            self.task.current_dir_id, save=False, all=True, limit=1000
        )
        if code == 0:
            for f in files:
                if str(f.get("FileId")) == str(self.task.file_id):
                    logger.debug("在当前目录中找到: %s", f.get("FileName"))
                    return f

        # 从 Pan123 list 中查找
        for f in self.pan.list:
            if str(f.get("FileId")) == str(self.task.file_id):
                logger.debug("从 list 中找到: %s", f.get("FileName"))
                return f

        # 从根目录查找
        code, files = self.pan.get_dir_by_id(0, save=False, all=True, limit=1000)
        if code == 0:
            for f in files:
                if str(f.get("FileId")) == str(self.task.file_id):
                    logger.debug("从根目录找到: %s", f.get("FileName"))
                    return f

        return None
