"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""


import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..common.config import ConfigManager
from ..common.log import get_logger
from ..common.i18n import tr
from ..common.transfer_store import TransferStore

logger = get_logger(__name__)


def _measure_speed(speed_ts, speed_bytes, current_speed, bytes_done):
    """实时速度计算（B/s）。

    相邻两次上报间隔 >= 0.5s 时按字节差/时间差计算，
    否则沿用当前速度，避免高频信号下抖动。

    Returns:
        (speed, new_ts, new_bytes)
    """
    now = time.monotonic()
    if speed_ts is None:
        return 0.0, now, bytes_done
    dt = now - speed_ts
    if dt >= 0.5:
        speed = (bytes_done - speed_bytes) / dt
        return max(speed, 0.0), now, bytes_done
    return current_speed, speed_ts, speed_bytes


class TransferTask:
    """传输任务基类"""

    # 优先级：0=低 1=普通 2=高
    PRIORITY_LOW = 0
    PRIORITY_NORMAL = 1
    PRIORITY_HIGH = 2

    def __init__(self, file_name, file_size, priority=PRIORITY_NORMAL):
        self.file_name = file_name
        self.file_size = file_size
        self.progress = 0
        self.speed = 0.0  # 实时速度（B/s），传输中更新
        self.status = tr("transfer.status_waiting", "等待中")
        self.priority = priority
        # 持久化任务 ID（由 TransferStore 分配），用于历史记录与断点续传
        self.task_id = None
        # 是否已记录历史（防止重复记录）
        self.history_recorded = False


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
    """上传线程（支持并行分片、速度限制、暂停/恢复）"""

    # (progress_percent, speed_bps)：进度百分比与实时速度（B/s）
    progress_updated = Signal(int, float)
    status_updated = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, task, pan):
        super().__init__()
        self.task = task
        self.pan = pan
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始状态：不暂停
        self._cancelled = False
        # 速度测量状态
        self._speed_ts = None
        self._speed_bytes = 0

    @property
    def is_cancelled(self):
        """供上传服务轮询的取消标志。"""
        return self._cancelled

    def wait_if_paused(self):
        """暂停时阻塞（由上传分片循环调用）。"""
        self._pause_event.wait()

    def pause(self):
        """暂停传输"""
        self._pause_event.clear()
        self.task.speed = 0.0
        self.status_updated.emit(tr("transfer.status_paused", "已暂停"))

    def resume(self):
        """恢复传输"""
        self._pause_event.set()
        self.status_updated.emit(tr("transfer.status_uploading", "上传中"))

    def cancel(self):
        """取消传输"""
        self._cancelled = True
        self._pause_event.set()  # 解除暂停以便退出

    def run(self):
        try:
            self._pause_event.wait()  # 检查是否立即暂停
            self.status_updated.emit(tr("transfer.status_uploading", "上传中"))
            logger.info(
                "上传线程启动: %s (%.2f MB)",
                self.task.file_name,
                self.task.file_size / 1024 / 1024,
            )

            ul_limit = ConfigManager.get_setting("uploadSpeedLimit", 0)
            self.pan.set_upload_speed_limit(ul_limit)
            ul_threads = ConfigManager.get_setting("uploadThreadCount", 1)
            logger.debug("上传分片线程数: %d", ul_threads)

            current_parent_id = self.pan.parent_file_id
            self.pan.parent_file_id = self.task.target_dir_id
            logger.debug("上传目标目录: %s", self.task.target_dir_id)

            # 断点续传：从持久化任务读取 S3 会话信息
            resume_info = None
            try:
                if self.task.task_id is not None:
                    store = TransferStore()
                    for row in store.get_active_tasks("upload"):
                        if row["id"] == self.task.task_id and row.get("resume_info"):
                            resume_info = json.loads(row["resume_info"])
                            break
            except Exception as e:
                logger.warning("读取上传续传信息失败: %s", e)

            def _on_session(session_info):
                """获得 S3 会话后持久化，供中断后断点续传。"""
                try:
                    if self.task.task_id is not None:
                        TransferStore().update_task(
                            self.task.task_id, resume_info=session_info
                        )
                except Exception as e:
                    logger.error("持久化上传会话失败: %s", e)

            def _on_upload_progress(uploaded_bytes):
                """上传进度回调：计算实时速度并更新 UI。"""
                if self._cancelled:
                    return
                speed, ts, b = _measure_speed(
                    self._speed_ts, self._speed_bytes,
                    self.task.speed, uploaded_bytes,
                )
                self._speed_ts, self._speed_bytes = ts, b
                self.task.speed = speed
                if self.task.file_size > 0:
                    pct = int(uploaded_bytes * 100 / self.task.file_size)
                else:
                    pct = 0
                self.progress_updated.emit(pct, speed)

            def _on_validation(percent):
                """MD5 校验进度回调：显示 '校验中 xx%'，完成后切回上传中。"""
                if self._cancelled:
                    return
                if percent >= 100:
                    self.status_updated.emit(tr("transfer.status_uploading", "上传中"))
                else:
                    self.status_updated.emit(
                        tr("transfer.status_validating", "校验中") + f" {percent}%"
                    )

            t0 = time.monotonic()
            if resume_info:
                self.status_updated.emit(tr("transfer.status_resuming", "续传中"))
            self.pan.up_load(
                self.task.local_path,
                task=self,
                resume_info=resume_info,
                session_callback=_on_session,
                num_threads=ul_threads,
                progress_callback=_on_upload_progress,
                validation_callback=_on_validation,
            )
            elapsed = time.monotonic() - t0

            self.pan.parent_file_id = current_parent_id

            if self._cancelled:
                self.task.speed = 0.0
                self.status_updated.emit(tr("transfer.status_cancelled", "已取消"))
                return

            self.task.speed = 0.0
            self.progress_updated.emit(100, 0.0)
            self.status_updated.emit(tr("transfer.status_completed", "已完成"))
            self.finished.emit()
            logger.info("上传完成: %s (%.1fs)", self.task.file_name, elapsed)
        except Exception as e:
            logger.error("上传失败: %s: %s", self.task.file_name, e)
            self.error.emit(str(e))
            self.status_updated.emit(tr("transfer.status_failed", "失败"))


class DownloadThread(QThread):
    """下载线程（支持多线程分片、速度限制、暂停/恢复）"""

    # (progress_percent, speed_bps)：进度百分比与实时速度（B/s）
    progress_updated = Signal(int, float)
    status_updated = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, task, pan):
        super().__init__()
        self.task = task
        self.pan = pan
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancelled = False
        self._cancel_event = threading.Event()
        # 速度测量状态
        self._speed_ts = None
        self._speed_bytes = 0

    def pause(self):
        """暂停传输"""
        self._pause_event.clear()
        self.task.speed = 0.0
        self.status_updated.emit(tr("transfer.status_paused", "已暂停"))

    def resume(self):
        """恢复传输"""
        self._pause_event.set()
        self.status_updated.emit(tr("transfer.status_downloading", "下载中"))

    def cancel(self):
        """取消传输"""
        self._cancelled = True
        self._cancel_event.set()  # 通知下载循环立即中止
        self._pause_event.set()

    def run(self):
        try:
            self.status_updated.emit(tr("transfer.status_downloading", "下载中"))
            logger.info(
                "下载线程启动: %s, file_id=%s, size=%.2f MB",
                self.task.file_name,
                self.task.file_id,
                self.task.file_size / 1024 / 1024,
            )

            multi_thread = ConfigManager.get_setting("multiThreadDownload", True)
            dl_limit = ConfigManager.get_setting("downloadSpeedLimit", 0)
            dl_threads = ConfigManager.get_setting("downloadThreadCount", 4)
            logger.debug(
                "下载配置: multi_thread=%s, threads=%d, speed_limit=%d KB/s",
                multi_thread,
                dl_threads,
                dl_limit,
            )

            self.pan.set_download_multi_thread(multi_thread, dl_threads)
            self.pan.set_download_speed_limit(dl_limit)

            def _on_progress(downloaded, total):
                if self._cancelled:
                    return
                self._pause_event.wait()  # 暂停时阻塞回调
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    speed, ts, b = _measure_speed(
                        self._speed_ts, self._speed_bytes,
                        self.task.speed, downloaded,
                    )
                    self._speed_ts, self._speed_bytes = ts, b
                    self.task.speed = speed
                    self.progress_updated.emit(pct, speed)

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

            # 断点续传：检测已存在的临时文件（.tmp）
            resume_offset = 0
            temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
            if temp_path.exists() and file_size > 0:
                partial = temp_path.stat().st_size
                if 0 < partial < file_size:
                    resume_offset = partial
                    self.status_updated.emit(tr("transfer.status_resuming", "续传中"))
                    logger.info(
                        "断点续传: %s 已下载 %d/%d 字节",
                        self.task.file_name, partial, file_size,
                    )
                elif partial >= file_size:
                    # 临时文件已完整，直接完成
                    if file_path.exists():
                        file_path.unlink()
                    temp_path.rename(file_path)
                    self.task.speed = 0.0
                    self.progress_updated.emit(100, 0.0)
                    self.status_updated.emit(tr("transfer.status_completed", "已完成"))
                    self.finished.emit()
                    return

            t0 = time.monotonic()
            success = self.pan.download_file(
                download_url,
                file_path,
                file_size,
                progress_callback=_on_progress,
                resume_offset=resume_offset,
                cancel_event=self._cancel_event,
            )
            elapsed = time.monotonic() - t0

            # 取消优先于失败处理：已取消时不报错，临时文件保留供续传
            if self._cancelled:
                self.task.speed = 0.0
                self.status_updated.emit(tr("transfer.status_cancelled", "已取消"))
                return

            if not success:
                raise RuntimeError("下载失败")

            self.task.speed = 0.0
            self.progress_updated.emit(100, 0.0)
            self.status_updated.emit(tr("transfer.status_completed", "已完成"))
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
            self.status_updated.emit(tr("transfer.status_failed", "失败"))

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
