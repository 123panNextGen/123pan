"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidgetItem,
    QFrame,
    QHBoxLayout,
)

from PySide6.QtCore import Qt, QTimer

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    SegmentedWidget,
    TableWidget,
    PushButton,
    InfoBar,
)

from ..common.style_sheet import StyleSheet
from ..common.utils import (
    configure_resizable_header,
    format_file_size,
    format_speed,
)
from ..common.config import ConfigManager
from ..common.transfer_store import (
    TransferStore,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_FAILED,
)

from ..common.log import get_logger
from ..common.i18n import tr

from ..tasks.transfer_tasks import (
    UploadTask,
    DownloadTask,
    UploadThread,
    DownloadThread,
)
from .transfer_table import TransferTableMixin

logger = get_logger(__name__)

# 默认最大并发传输数
_DEFAULT_MAX_CONCURRENT = 3
_THREAD_CANCEL_WAIT_MS = 15000


class TransferInterface(QWidget, TransferTableMixin):
    """传输页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("TransferInterface")

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        self.upload_tasks = []
        self.download_tasks = []
        self.upload_threads = []
        self.download_threads = []
        self.pan = None  # Pan123实例

        # 传输任务持久化（历史记录 / 断点续传）
        self._store = TransferStore()

        # 并发控制
        self._pending_upload_queue = []  # 待处理上传队列: [(file_name, file_size, local_path, target_dir_id), ...]
        self._pending_download_queue = []  # 待处理下载队列: [(file_name, file_size, file_id, save_path, current_dir_id), ...]
        self._active_upload_count = 0
        self._active_download_count = 0
        self._max_concurrent_uploads = ConfigManager.get_setting(
            "maxConcurrentUploads", _DEFAULT_MAX_CONCURRENT
        )
        self._max_concurrent_downloads = ConfigManager.get_setting(
            "maxConcurrentDownloads", _DEFAULT_MAX_CONCURRENT
        )

        # 总速度汇总定时刷新（每秒）
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(1000)
        self._speed_timer.timeout.connect(self.__update_total_speed)
        self._speed_timer.start()

        self.__createTopBar()
        self.__createContent()
        self.__initWidget()

    def set_pan(self, pan):
        """设置Pan123实例"""
        self.pan = pan
        # 应用代理和速度限制配置
        self._apply_proxy_settings()
        self._apply_speed_settings()

    def update_concurrent_limits(self, max_uploads=None, max_downloads=None):
        """动态更新并发传输上限（由设置页面触发）。"""
        if max_uploads is not None:
            self._max_concurrent_uploads = max_uploads
        if max_downloads is not None:
            self._max_concurrent_downloads = max_downloads
        # 更新限制后尝试处理待处理队列
        self._process_pending_queues()

    def shutdown(self):
        """应用退出：取消所有进行中的传输线程并等待其结束。

        避免退出时 QThread 对象被销毁而线程仍在运行
        （"QThread: Destroyed while thread is still running"）。
        已取消/已排队任务由 TransferStore 持久化，下次启动可恢复。
        """
        threads = list(self.upload_threads) + list(self.download_threads)
        if not threads:
            return
        # 1. 请求取消（上传/下载均会在分片边界退出）
        for thread in threads:
            thread.cancel()
        # 2. 断开信号并从列表移除，避免退出过程中回调触发排队任务/UI 更新
        for thread in threads:
            self.__cleanup_thread(
                thread,
                "upload" if isinstance(thread, UploadThread) else "download",
            )
        # 3. 等待线程真正结束（超时兜底，避免卡死退出）
        for thread in threads:
            if thread.isRunning():
                thread.wait(_THREAD_CANCEL_WAIT_MS)
        self.upload_threads.clear()
        self.download_threads.clear()

    def _apply_proxy_settings(self):
        """从配置读取并应用代理设置。"""
        if not self.pan:
            return
        enabled = ConfigManager.get_setting("proxyEnabled", False)
        if enabled:
            proxy_type = ConfigManager.get_setting("proxyType", "http")
            host = ConfigManager.get_setting("proxyHost", "")
            port = ConfigManager.get_setting("proxyPort", 0)
            username = ConfigManager.get_setting("proxyUsername", "")
            password = ConfigManager.get_setting("proxyPassword", "")
            if host and port > 0:
                self.pan.set_download_proxy(
                    proxy_type, host, port, username, password
                )
                logger.info("代理已启用: %s://%s:%s", proxy_type, host, port)
        else:
            self.pan.clear_download_proxy()

    def _apply_speed_settings(self):
        """从配置读取并应用速度限制与分片线程设置。"""
        if not self.pan:
            return
        dl_limit = ConfigManager.get_setting("downloadSpeedLimit", 0)
        ul_limit = ConfigManager.get_setting("uploadSpeedLimit", 0)
        multi_thread = ConfigManager.get_setting("multiThreadDownload", True)
        dl_threads = ConfigManager.get_setting("downloadThreadCount", 4)

        self.pan.set_download_multi_thread(multi_thread, dl_threads)
        self.pan.set_download_speed_limit(dl_limit)
        self.pan.set_upload_speed_limit(ul_limit)

    def __createTopBar(self):
        self.topBarFrame = QFrame(self)
        self.topBarFrame.setObjectName("frame")
        self.topBarLayout = QHBoxLayout(self.topBarFrame)
        self.topBarLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarLayout.setSpacing(8)

        self.titleLabel = QLabel(tr("transfer.title", "传输管理"), self.topBarFrame)
        self.segmentedWidget = SegmentedWidget(self.topBarFrame)

        # 添加分段项
        self.segmentedWidget.addItem(routeKey="upload", icon=FIF.UP.icon(), text=tr("transfer.upload_tab", "上传"))
        self.segmentedWidget.addItem(
            routeKey="download", icon=FIF.DOWNLOAD.icon(), text=tr("transfer.download_tab", "下载")
        )
        self.segmentedWidget.addItem(
            routeKey="history", icon=FIF.HISTORY.icon(), text=tr("transfer.history_tab", "历史记录")
        )
        self.segmentedWidget.setCurrentItem("upload")

        # 顶栏汇总速度标签（每秒刷新）
        self.uploadTotalSpeedLabel = QLabel(
            tr("transfer.total_upload_speed", "↑ 上传 --"), self.topBarFrame
        )
        self.downloadTotalSpeedLabel = QLabel(
            tr("transfer.total_download_speed", "↓ 下载 --"), self.topBarFrame
        )
        for lbl in (self.uploadTotalSpeedLabel, self.downloadTotalSpeedLabel):
            lbl.setStyleSheet("color: gray; font-size: 12px;")

        self.clearCompletedButton = PushButton(
            FIF.DELETE.icon(), tr("transfer.clear_completed", "清除已完成"), self.topBarFrame
        )

        self.topBarLayout.addWidget(self.titleLabel)
        self.topBarLayout.addWidget(self.segmentedWidget)
        self.topBarLayout.addStretch(1)
        self.topBarLayout.addWidget(self.uploadTotalSpeedLabel, 0)
        self.topBarLayout.addWidget(self.downloadTotalSpeedLabel, 0)
        self.topBarLayout.addSpacing(8)
        self.topBarLayout.addWidget(self.clearCompletedButton, 0)

        self.mainLayout.addWidget(self.topBarFrame)

    def __createContent(self):
        # 上传表格
        self.uploadFrame = QFrame(self)
        self.uploadFrame.setObjectName("frame")
        self.uploadLayout = QVBoxLayout(self.uploadFrame)
        self.uploadLayout.setContentsMargins(0, 8, 0, 0)

        self.uploadTable = TableWidget(self.uploadFrame)
        self.uploadTable.setAlternatingRowColors(True)
        self.uploadTable.setColumnCount(8)
        self.uploadTable.setHorizontalHeaderLabels(
            [tr("transfer.col_name", "文件名"), tr("transfer.col_priority", "优先级"), tr("transfer.col_size", "大小"), tr("transfer.col_speed", "速度"), tr("transfer.col_progress", "进度"), tr("transfer.col_percent", "百分比"), tr("transfer.col_status", "状态"), tr("transfer.col_action", "操作")]
        )
        self.uploadTable.setBorderRadius(8)
        self.uploadTable.setBorderVisible(True)

        # 所有列可交互调整列宽，文件名列吸收多余宽度
        configure_resizable_header(
            self.uploadTable,
            stretch_column=0,
            default_widths={0: 260, 1: 80, 2: 100, 3: 100, 4: 160, 5: 60, 6: 90, 7: 140},
        )

        self.uploadLayout.addWidget(self.uploadTable)
        self.uploadEmptyLabel = self.__make_empty_label(
            tr("transfer.state_empty", "暂无上传任务"), self.uploadFrame
        )
        self.uploadLayout.addWidget(self.uploadEmptyLabel)

        # 下载表格
        self.downloadFrame = QFrame(self)
        self.downloadFrame.setObjectName("frame")
        self.downloadLayout = QVBoxLayout(self.downloadFrame)
        self.downloadLayout.setContentsMargins(0, 8, 0, 0)

        self.downloadTable = TableWidget(self.downloadFrame)
        self.downloadTable.setAlternatingRowColors(True)
        self.downloadTable.setColumnCount(8)
        self.downloadTable.setHorizontalHeaderLabels(
            [tr("transfer.col_name", "文件名"), tr("transfer.col_priority", "优先级"), tr("transfer.col_size", "大小"), tr("transfer.col_speed", "速度"), tr("transfer.col_progress", "进度"), tr("transfer.col_percent", "百分比"), tr("transfer.col_status", "状态"), tr("transfer.col_action", "操作")]
        )
        self.downloadTable.setBorderRadius(8)
        self.downloadTable.setBorderVisible(True)

        # 所有列可交互调整列宽，文件名列吸收多余宽度
        configure_resizable_header(
            self.downloadTable,
            stretch_column=0,
            default_widths={0: 260, 1: 80, 2: 100, 3: 100, 4: 160, 5: 60, 6: 90, 7: 140},
        )

        self.downloadLayout.addWidget(self.downloadTable)
        self.downloadEmptyLabel = self.__make_empty_label(
            tr("transfer.state_empty_dl", "暂无下载任务"), self.downloadFrame
        )
        self.downloadLayout.addWidget(self.downloadEmptyLabel)

        # 历史记录表格
        self.historyFrame = QFrame(self)
        self.historyFrame.setObjectName("frame")
        self.historyLayout = QVBoxLayout(self.historyFrame)
        self.historyLayout.setContentsMargins(0, 8, 0, 0)

        history_header = QHBoxLayout()
        self.clearHistoryButton = PushButton(
            FIF.DELETE.icon(), tr("transfer.clear_history", "清空历史"), self.historyFrame
        )
        self.clearHistoryButton.clicked.connect(self.__clear_history)
        history_header.addStretch()
        history_header.addWidget(self.clearHistoryButton)
        self.historyLayout.addLayout(history_header)

        self.historyTable = TableWidget(self.historyFrame)
        self.historyTable.setAlternatingRowColors(True)
        self.historyTable.setColumnCount(5)
        self.historyTable.setHorizontalHeaderLabels(
            [
                tr("transfer.col_type", "类型"),
                tr("transfer.col_name", "文件名"),
                tr("transfer.col_size", "大小"),
                tr("transfer.col_status", "状态"),
                tr("transfer.col_time", "时间"),
            ]
        )
        self.historyTable.setBorderRadius(8)
        self.historyTable.setBorderVisible(True)

        # 所有列可交互调整列宽，文件名列吸收多余宽度
        configure_resizable_header(
            self.historyTable,
            stretch_column=1,
            default_widths={0: 80, 1: 300, 2: 100, 3: 90, 4: 160},
        )
        self.historyLayout.addWidget(self.historyTable)
        self.historyEmptyLabel = self.__make_empty_label(
            tr("transfer.state_empty_his", "暂无历史记录"), self.historyFrame
        )
        self.historyLayout.addWidget(self.historyEmptyLabel)

        # 默认显示上传表格
        self.downloadFrame.hide()
        self.historyFrame.hide()

        self.mainLayout.addWidget(self.uploadFrame)
        self.mainLayout.addWidget(self.downloadFrame)
        self.mainLayout.addWidget(self.historyFrame)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()

    @staticmethod
    def __make_empty_label(text, parent):
        """创建表格空状态提示标签。"""
        from PySide6.QtWidgets import QLabel

        label = QLabel(text, parent)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 14px;")
        label.hide()
        return label

    def __connectSignalToSlot(self):
        self.segmentedWidget.currentItemChanged.connect(self.__onSegmentChanged)
        self.clearCompletedButton.clicked.connect(self.__clearCompletedTasks)
        self.clearHistoryButton.clicked.connect(self.__clear_history)

    def __onSegmentChanged(self, routeKey):
        if routeKey == "upload":
            self.uploadFrame.show()
            self.downloadFrame.hide()
            self.historyFrame.hide()
        elif routeKey == "download":
            self.uploadFrame.hide()
            self.downloadFrame.show()
            self.historyFrame.hide()
        else:
            self.uploadFrame.hide()
            self.downloadFrame.hide()
            self.historyFrame.show()
            self.__refresh_history()

    def add_upload_task(self, file_name, file_size, local_path, target_dir_id):
        """添加上传任务。

        若当前活跃上传数已达上限，任务进入等待队列；
        否则立即启动上传线程。
        """
        task = UploadTask(file_name, file_size, local_path, target_dir_id)
        self.upload_tasks.append(task)
        logger.info("添加上传任务: %s (%.2f MB)", file_name, file_size / 1024 / 1024)
        task.task_id = self._store.add_task(
            "upload",
            task.file_name,
            task.file_size,
            priority=task.priority,
            status=STATUS_QUEUED,
            local_path=task.local_path,
            target_dir_id=task.target_dir_id,
        )
        self.__update_upload_table()

        if not self.pan:
            return task

        if self._active_upload_count >= self._max_concurrent_uploads:
            self._pending_upload_queue.append(task)
            task.status = tr("transfer.status_queued", "排队中")
            self.__update_upload_table()
            logger.debug(
                "上传任务排队: %s (活跃: %d/%d)",
                file_name,
                self._active_upload_count,
                self._max_concurrent_uploads,
            )
            return task

        self.__start_upload_thread(task)
        return task

    def __start_upload_thread(self, task):
        """启动单个上传线程。"""
        thread = UploadThread(task, self.pan)
        # MD5 校验可能耗时，启动线程前先给出明确的非空状态和初始进度。
        task.status = tr("transfer.status_validating", "校验中") + " 0%"
        task.progress = 0
        self.__update_upload_table()
        thread.progress_updated.connect(
            lambda progress, speed, t=task: self.__update_task_progress(
                t, progress, speed
            )
        )
        thread.status_updated.connect(
            lambda status, t=task: self.__update_task_status(t, status)
        )
        thread.completed.connect(
            lambda t=task, th=thread: self.__on_thread_finished(t, th, "upload")
        )
        thread.error.connect(
            lambda err, t=task, th=thread: self.__on_thread_error(t, th, err)
        )
        self.upload_threads.append(thread)
        self._active_upload_count += 1
        if task.task_id is not None:
            self._store.update_task(task.task_id, status=STATUS_RUNNING)
        thread.start()
        logger.debug(
            "上传线程已启动: %s (活跃: %d/%d)",
            task.file_name,
            self._active_upload_count,
            self._max_concurrent_uploads,
        )

    def add_download_task(
        self, file_name, file_size, file_id, save_path, current_dir_id=0
    ):
        """添加下载任务。

        若当前活跃下载数已达上限，任务进入等待队列；
        否则立即启动下载线程。
        """
        task = DownloadTask(file_name, file_size, file_id, save_path, current_dir_id)
        self.download_tasks.append(task)
        logger.info(
            "添加下载任务: %s (%.2f MB, id=%s)",
            file_name,
            file_size / 1024 / 1024,
            file_id,
        )
        task.task_id = self._store.add_task(
            "download",
            task.file_name,
            task.file_size,
            priority=task.priority,
            status=STATUS_QUEUED,
            local_path=task.save_path,
            file_id=task.file_id,
            current_dir_id=task.current_dir_id,
        )
        self.__update_download_table()

        if not self.pan:
            return task

        if self._active_download_count >= self._max_concurrent_downloads:
            self._pending_download_queue.append(task)
            task.status = tr("transfer.status_queued", "排队中")
            self.__update_download_table()
            logger.debug(
                "下载任务排队: %s (活跃: %d/%d)",
                file_name,
                self._active_download_count,
                self._max_concurrent_downloads,
            )
            return task

        self.__start_download_thread(task)
        return task

    def __start_download_thread(self, task):
        """启动单个下载线程。"""
        thread = DownloadThread(task, self.pan)
        thread.progress_updated.connect(
            lambda progress, speed, t=task: self.__update_task_progress(
                t, progress, speed
            )
        )
        thread.status_updated.connect(
            lambda status, t=task: self.__update_task_status(t, status)
        )
        thread.completed.connect(
            lambda t=task, th=thread: self.__on_thread_finished(t, th, "download")
        )
        thread.error.connect(
            lambda err, t=task, th=thread: self.__on_thread_error(t, th, err)
        )
        self.download_threads.append(thread)
        self._active_download_count += 1
        if task.task_id is not None:
            self._store.update_task(task.task_id, status=STATUS_RUNNING)
        thread.start()
        logger.debug(
            "下载线程已启动: %s (活跃: %d/%d)",
            task.file_name,
            self._active_download_count,
            self._max_concurrent_downloads,
        )

    def __update_task_progress(self, task, progress, speed=0.0):
        """更新任务进度与实时速度（只刷新变更行，避免遍历整表）。"""
        task.progress = progress
        task.speed = speed
        self.__update_single_task_row(task)

    def __update_task_status(self, task, status):
        """更新任务状态（只刷新变更行）。"""
        task.status = status
        self.__update_single_task_row(task)

    def __update_single_task_row(self, task):
        """仅更新任务所在行。

        进度/状态信号高频触发（约 10 次/秒/任务），若每次遍历全部任务
        并逐行比对状态，任务数量多时会放大 UI 开销。这里直接定位
        任务在列表中的行号，只重绘该行。
        """
        if isinstance(task, UploadTask):
            table = self.uploadTable
            tasks = self.upload_tasks
            task_type = "upload"
        elif isinstance(task, DownloadTask):
            table = self.downloadTable
            tasks = self.download_tasks
            task_type = "download"
        else:
            return

        try:
            row = tasks.index(task)
        except ValueError:
            return
        if row < 0 or row >= table.rowCount():
            return
        self._update_row(table, task, row, task_type)

    def __on_thread_finished(self, task, thread, task_type):
        """线程完成回调：更新 UI、清理线程资源、启动下一个等待任务。"""
        logger.info("任务完成: type=%s, name=%s", task_type, task.file_name)
        self.__cleanup_thread(thread, task_type)
        if task_type == "upload":
            self._active_upload_count -= 1
            self.__update_upload_table()
            self.__start_next_pending_upload()
            # 上传成功后云端目录内容已变化：失效缓存并刷新当前目录，
            # 避免文件列表显示旧缓存导致新上传文件不出现
            self._invalidate_upload_dir(task)
            InfoBar.success(
                title=tr("transfer.msg_upload_complete", "上传完成"),
                content=tr("transfer.msg_file_uploaded", "文件 '{}' 上传成功").format(task.file_name),
                parent=self,
            )
        else:
            self._active_download_count -= 1
            self.__update_download_table()
            self.__start_next_pending_download()
        self.__record_history(task, task_type)

    def _invalidate_upload_dir(self, task):
        """上传完成后失效目标目录缓存；若用户正浏览该目录则强制刷新列表。"""
        try:
            target_dir_id = getattr(task, "target_dir_id", None)
            if target_dir_id is None or not self.pan:
                return
            self.pan.mark_dir_dirty(target_dir_id)
            # 当前正浏览上传目标目录时，立即强制刷新（跳过缓存）
            mw = self.window()
            if mw is not None and hasattr(mw, "file_interface"):
                fi = mw.file_interface
                if fi is not None and getattr(fi, "current_dir_id", None) == int(target_dir_id):
                    logger.debug("上传完成，刷新当前目录: %s", target_dir_id)
                    fi._loadCurrentList(force_refresh=True)
        except Exception as e:
            logger.error("上传后刷新目录失败: %s", e)

    def __on_thread_error(self, task, thread, error):
        """线程错误回调：更新 UI、清理线程资源、启动下一个等待任务。"""
        logger.error(
            "任务失败: type=%s, name=%s, error=%s",
            type(task).__name__,
            task.file_name,
            error,
        )
        task_type = "upload" if isinstance(task, UploadTask) else "download"
        self.__cleanup_thread(thread, task_type)
        if task_type == "upload":
            self._active_upload_count -= 1
            self.__update_upload_table()
            self.__start_next_pending_upload()
        else:
            self._active_download_count -= 1
            self.__update_download_table()
            self.__start_next_pending_download()
        # 上传失败保留活动任务记录（含 S3 会话），支持重试续传
        self.__record_history(task, task_type, keep_active=(task_type == "upload"))

    def __cleanup_thread(self, thread, task_type):
        """断开线程所有信号并从列表中移除，释放资源。"""
        try:
            thread.progress_updated.disconnect()
        except TypeError:
            pass
        try:
            thread.status_updated.disconnect()
        except TypeError:
            pass
        try:
            thread.completed.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            thread.error.disconnect()
        except TypeError:
            pass
        thread_list = self.upload_threads if task_type == "upload" else self.download_threads
        if thread in thread_list:
            thread_list.remove(thread)
        if not thread.isFinished():
            thread.quit()
            thread.wait(_THREAD_CANCEL_WAIT_MS)

    def __clearCompletedTasks(self):
        """清除所有已完成/已取消/失败的任务"""
        route = self.segmentedWidget.currentRouteKey()
        if route == "history":
            # 历史记录页：直接清空历史
            self._store.clear_history()
            self.__refresh_history()
            InfoBar.success(
                title=tr("transfer.msg_history_cleared", "已清空"),
                content=tr("transfer.msg_history_cleared_desc", "传输历史已清空"),
                parent=self,
            )
            return
        if route == "upload":
            tasks = self.upload_tasks
            threads = self.upload_threads
        else:
            tasks = self.download_tasks
            threads = self.download_threads

        removed = 0
        for task in list(tasks):
            if task.status in (tr("transfer.status_completed", "已完成"), tr("transfer.status_cancelled", "已取消"), tr("transfer.status_failed", "失败")):
                # 清理关联线程（已完成任务的线程计数已由回调处理，此处仅清理线程资源）
                for t in list(threads):
                    if t.task is task:
                        self.__cleanup_thread(t, route)
                        break
                tasks.remove(task)
                removed += 1

        if removed > 0:
            if route == "upload":
                self.__update_upload_table()
                self.__start_next_pending_upload()
            else:
                self.__update_download_table()
                self.__start_next_pending_download()
            InfoBar.success(
                title=tr("transfer.msg_cleanup_done", "清理完成"),
                content=tr("transfer.msg_cleaned_tasks", "已清除 {} 个已完成任务").format(removed),
                parent=self,
            )
        else:
            InfoBar.info(
                title=tr("transfer.msg_no_cleanup", "无需清理"),
                content=tr("transfer.msg_no_completed_tasks", "没有已完成的任务"),
                parent=self,
            )

    def _pause_task(self, task, task_type):
        """暂停任务"""
        thread_list = (
            self.upload_threads if task_type == "upload" else self.download_threads
        )
        for t in thread_list:
            if t.task is task:
                t.pause()
                if task_type == "upload":
                    self.__update_upload_table()
                else:
                    self.__update_download_table()
                return

    def _resume_task(self, task, task_type):
        """恢复任务"""
        thread_list = (
            self.upload_threads if task_type == "upload" else self.download_threads
        )
        for t in thread_list:
            if t.task is task:
                t.resume()
                if task_type == "upload":
                    self.__update_upload_table()
                else:
                    self.__update_download_table()
                return

    def _remove_task(self, task, task_type):
        """删除任务及其关联线程。同时从等待队列中移除（若在队列中）。"""
        # 移除活动任务时记录历史（已完成/失败任务此前已记录，这里防重复）
        self.__record_history(task, task_type)
        # 显式清理活动任务记录（含续传会话），用户删除后不再保留
        if getattr(task, "task_id", None) is not None:
            self._store.remove_task(task.task_id)
            task.task_id = None
        if task_type == "upload":
            if task in self.upload_tasks:
                self.upload_tasks.remove(task)
                # 查找并清理关联线程
                thread_found = False
                for t in list(self.upload_threads):
                    if t.task is task:
                        t.cancel()
                        self.__cleanup_thread(t, "upload")
                        self._active_upload_count -= 1
                        thread_found = True
                        break
                # 若线程未找到，任务可能在等待队列中——需要从队列移除
                if not thread_found:
                    self._remove_from_pending_queue(task, "upload")
                self.__update_upload_table()
                if thread_found:
                    self.__start_next_pending_upload()
        else:
            if task in self.download_tasks:
                self.download_tasks.remove(task)
                # 查找并清理关联线程
                thread_found = False
                for t in list(self.download_threads):
                    if t.task is task:
                        t.cancel()
                        self.__cleanup_thread(t, "download")
                        self._active_download_count -= 1
                        thread_found = True
                        break
                # 若线程未找到，任务可能在等待队列中——需要从队列移除
                if not thread_found:
                    self._remove_from_pending_queue(task, "download")
                self.__update_download_table()
                if thread_found:
                    self.__start_next_pending_download()

    def _remove_from_pending_queue(self, task, task_type):
        """从等待队列中移除任务。"""
        if task_type == "upload":
            if task in self._pending_upload_queue:
                self._pending_upload_queue.remove(task)
        else:
            if task in self._pending_download_queue:
                self._pending_download_queue.remove(task)

    @staticmethod
    def _pick_next_pending(queue):
        """选择优先级最高的排队任务（同优先级保持先入先出）。

        队列中存储的是任务对象，直接按 priority 取最大；
        max 对同键值返回最先出现的元素，天然满足 FIFO。
        """
        if not queue:
            return None
        return max(queue, key=lambda t: t.priority)

    def __start_next_pending_upload(self):
        """填满空闲上传槽位，每次选择最高优先级任务。"""
        started = False
        while (
            self._pending_upload_queue
            and self._active_upload_count < self._max_concurrent_uploads
        ):
            task = self._pick_next_pending(self._pending_upload_queue)
            if task is None:
                break
            self._pending_upload_queue.remove(task)
            if task.status == tr("transfer.status_queued", "排队中"):
                task.status = tr("transfer.status_waiting", "等待中")
            self.__start_upload_thread(task)
            started = True
        if started:
            self.__update_upload_table()

    def __start_next_pending_download(self):
        """填满空闲下载槽位，每次选择最高优先级任务。"""
        started = False
        while (
            self._pending_download_queue
            and self._active_download_count < self._max_concurrent_downloads
        ):
            task = self._pick_next_pending(self._pending_download_queue)
            if task is None:
                break
            self._pending_download_queue.remove(task)
            if task.status == tr("transfer.status_queued", "排队中"):
                task.status = tr("transfer.status_waiting", "等待中")
            self.__start_download_thread(task)
            started = True
        if started:
            self.__update_download_table()

    def _process_pending_queues(self):
        """处理两个待处理队列（当并发限制变更时调用）。"""
        self.__start_next_pending_upload()
        self.__start_next_pending_download()

    def _change_priority(self, task, task_type, priority):
        """修改任务优先级（0=低 1=普通 2=高）。"""
        task.priority = int(priority)
        logger.info(
            "修改任务优先级: type=%s, name=%s, priority=%s",
            task_type, task.file_name, priority,
        )

    def _retry_task(self, task, task_type):
        """重试失败任务（上传复用 S3 会话、下载复用临时文件，均断点续传）。"""
        # 清理可能残留的线程
        thread_list = (
            self.upload_threads if task_type == "upload" else self.download_threads
        )
        for t in list(thread_list):
            if t.task is task:
                self.__cleanup_thread(t, task_type)
                break

        task.status = tr("transfer.status_waiting", "等待中")
        task.progress = 0
        task.history_recorded = False

        # 重新建立活动任务记录（若此前已清理）
        if getattr(task, "task_id", None) is None:
            if task_type == "upload":
                task.task_id = self._store.add_task(
                    "upload", task.file_name, task.file_size,
                    priority=task.priority, status=STATUS_QUEUED,
                    local_path=task.local_path, target_dir_id=task.target_dir_id,
                )
            else:
                task.task_id = self._store.add_task(
                    "download", task.file_name, task.file_size,
                    priority=task.priority, status=STATUS_QUEUED,
                    local_path=task.save_path, file_id=task.file_id,
                    current_dir_id=task.current_dir_id,
                )

        if task_type == "upload":
            if self._active_upload_count >= self._max_concurrent_uploads:
                task.status = tr("transfer.status_queued", "排队中")
                self._pending_upload_queue.append(task)
                self.__update_upload_table()
                return
            self.__start_upload_thread(task)
            self.__update_upload_table()
        else:
            if self._active_download_count >= self._max_concurrent_downloads:
                task.status = tr("transfer.status_queued", "排队中")
                self._pending_download_queue.append(task)
                self.__update_download_table()
                return
            self.__start_download_thread(task)
            self.__update_download_table()

    def __update_upload_table(self):
        self._update_table(self.uploadTable, self.upload_tasks, "upload")
        self.uploadEmptyLabel.setVisible(not bool(self.upload_tasks))

    def __update_download_table(self):
        self._update_table(self.downloadTable, self.download_tasks, "download")
        self.downloadEmptyLabel.setVisible(not bool(self.download_tasks))

    def __update_total_speed(self):
        """汇总当前上传/下载总速度并更新顶栏标签（由 QTimer 周期触发）。"""
        ul_speed = sum(t.speed for t in self.upload_tasks)
        dl_speed = sum(t.speed for t in self.download_tasks)
        self.uploadTotalSpeedLabel.setText(
            tr("transfer.total_upload_speed", "↑ 上传 {}").format(format_speed(ul_speed))
        )
        self.downloadTotalSpeedLabel.setText(
            tr("transfer.total_download_speed", "↓ 下载 {}").format(format_speed(dl_speed))
        )

    # ---- 历史记录 ----

    def __record_history(self, task, task_type, keep_active=False):
        """记录任务历史。

        keep_active=True 时保留活动任务记录（上传失败保留 S3 会话供续传），
        否则记录后移除活动任务。history_recorded 防止重复记录。
        """
        if getattr(task, "history_recorded", False):
            return
        try:
            self._store.add_history(
                task_type, task.file_name, task.file_size, task.status
            )
            task.history_recorded = True
            if getattr(task, "task_id", None) is not None:
                if keep_active:
                    self._store.update_task(task.task_id, status=STATUS_FAILED)
                else:
                    self._store.remove_task(task.task_id)
                    task.task_id = None
            logger.debug("已记录传输历史: %s (%s)", task.file_name, task.status)
        except Exception as e:
            logger.error("记录传输历史失败: %s", e)

    def __refresh_history(self):
        """刷新历史记录表格。"""
        rows = self._store.get_history(limit=500)
        count = len(rows)
        self.historyTable.setRowCount(count)
        self.historyEmptyLabel.setVisible(count == 0)
        self.historyTable.setUpdatesEnabled(False)
        try:
            for i, row in enumerate(rows):
                type_text = (
                    tr("transfer.type_upload", "上传")
                    if row["task_type"] == "upload"
                    else tr("transfer.type_download", "下载")
                )
                self.historyTable.setItem(i, 0, QTableWidgetItem(type_text))
                self.historyTable.setItem(i, 1, QTableWidgetItem(row["file_name"]))
                self.historyTable.setItem(
                    i, 2, QTableWidgetItem(format_file_size(row["file_size"]))
                )
                self.historyTable.setItem(i, 3, QTableWidgetItem(row["status"]))
                # 时间展示（截断毫秒）
                finished = row["finished_at"] or ""
                display = str(finished).replace("T", " ").split(".", maxsplit=1)[0]
                self.historyTable.setItem(i, 4, QTableWidgetItem(display))
        finally:
            self.historyTable.setUpdatesEnabled(True)

    def __clear_history(self):
        """清空历史记录。"""
        self._store.clear_history()
        self.__refresh_history()
        InfoBar.success(
            title=tr("transfer.msg_history_cleared", "已清空"),
            content=tr("transfer.msg_history_cleared_desc", "传输历史已清空"),
            parent=self,
        )
