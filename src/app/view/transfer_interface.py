from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidgetItem,
    QFrame,
    QHBoxLayout,
)

from PyQt6.QtCore import Qt
from pathlib import Path

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    SegmentedWidget,
    TableWidget,
    PushButton,
    ProgressBar,
    InfoBar,
)

from ..common.style_sheet import StyleSheet
from ..common.utils import format_file_size
from ..common.config import ConfigManager

from ..common.log import get_logger

from ..tasks.transfer_tasks import (
    UploadTask,
    DownloadTask,
    UploadThread,
    DownloadThread,
)

logger = get_logger(__name__)


class TransferInterface(QWidget):
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

        self.__createTopBar()
        self.__createContent()
        self.__initWidget()

    def set_pan(self, pan):
        """设置Pan123实例"""
        self.pan = pan
        # 应用代理和速度限制配置
        self._apply_proxy_settings()
        self._apply_speed_settings()

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
                logger.info(f"代理已启用: {proxy_type}://{host}:{port}")
        else:
            self.pan.clear_download_proxy()

    def _apply_speed_settings(self):
        """从配置读取并应用速度限制设置。"""
        if not self.pan:
            return
        dl_limit = ConfigManager.get_setting("downloadSpeedLimit", 0)
        ul_limit = ConfigManager.get_setting("uploadSpeedLimit", 0)
        multi_thread = ConfigManager.get_setting("multiThreadDownload", True)

        self.pan.set_download_multi_thread(multi_thread)
        self.pan.set_download_speed_limit(dl_limit)
        self.pan.set_upload_speed_limit(ul_limit)

    def __createTopBar(self):
        self.topBarFrame = QFrame(self)
        self.topBarFrame.setObjectName("frame")
        self.topBarLayout = QHBoxLayout(self.topBarFrame)
        self.topBarLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarLayout.setSpacing(8)

        self.titleLabel = QLabel("传输管理", self.topBarFrame)
        self.segmentedWidget = SegmentedWidget(self.topBarFrame)

        # 添加分段项
        self.segmentedWidget.addItem(routeKey="upload", icon=FIF.UP.icon(), text="上传")
        self.segmentedWidget.addItem(
            routeKey="download", icon=FIF.DOWNLOAD.icon(), text="下载"
        )
        self.segmentedWidget.setCurrentItem("upload")

        self.topBarLayout.addWidget(self.titleLabel)
        self.topBarLayout.addWidget(self.segmentedWidget)

        self.mainLayout.addWidget(self.topBarFrame)

    def __createContent(self):
        # 上传表格
        self.uploadFrame = QFrame(self)
        self.uploadFrame.setObjectName("frame")
        self.uploadLayout = QVBoxLayout(self.uploadFrame)
        self.uploadLayout.setContentsMargins(0, 8, 0, 0)

        self.uploadTable = TableWidget(self.uploadFrame)
        self.uploadTable.setAlternatingRowColors(True)
        self.uploadTable.setColumnCount(6)
        self.uploadTable.setHorizontalHeaderLabels(
            ["文件名", "大小", "进度", "百分比", "状态", "操作"]
        )
        self.uploadTable.setBorderRadius(8)
        self.uploadTable.setBorderVisible(True)

        # 设置列宽
        header = self.uploadTable.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, header.ResizeMode.Stretch)
            header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(5, header.ResizeMode.ResizeToContents)

        self.uploadLayout.addWidget(self.uploadTable)

        # 下载表格
        self.downloadFrame = QFrame(self)
        self.downloadFrame.setObjectName("frame")
        self.downloadLayout = QVBoxLayout(self.downloadFrame)
        self.downloadLayout.setContentsMargins(0, 8, 0, 0)

        self.downloadTable = TableWidget(self.downloadFrame)
        self.downloadTable.setAlternatingRowColors(True)
        self.downloadTable.setColumnCount(6)
        self.downloadTable.setHorizontalHeaderLabels(
            ["文件名", "大小", "进度", "百分比", "状态", "操作"]
        )
        self.downloadTable.setBorderRadius(8)
        self.downloadTable.setBorderVisible(True)

        # 设置列宽
        header = self.downloadTable.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, header.ResizeMode.Stretch)
            header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, header.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(5, header.ResizeMode.ResizeToContents)

        self.downloadLayout.addWidget(self.downloadTable)

        # 默认显示上传表格
        self.downloadFrame.hide()

        self.mainLayout.addWidget(self.uploadFrame)
        self.mainLayout.addWidget(self.downloadFrame)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()

    def __connectSignalToSlot(self):
        self.segmentedWidget.currentItemChanged.connect(self.__onSegmentChanged)

    def __onSegmentChanged(self, routeKey):
        if routeKey == "upload":
            self.uploadFrame.show()
            self.downloadFrame.hide()
        else:
            self.uploadFrame.hide()
            self.downloadFrame.show()

    def add_upload_task(self, file_name, file_size, local_path, target_dir_id):
        """添加上传任务"""
        task = UploadTask(file_name, file_size, local_path, target_dir_id)
        self.upload_tasks.append(task)
        logger.info("添加上传任务: %s (%.2f MB)", file_name, file_size / 1024 / 1024)
        self.__update_upload_table()

        if self.pan:
            thread = UploadThread(task, self.pan)
            thread.progress_updated.connect(
                lambda progress, t=task: self.__update_task_progress(t, progress)
            )
            thread.status_updated.connect(
                lambda status, t=task: self.__update_task_status(t, status)
            )
            thread.finished.connect(
                lambda t=task, th=thread: self.__on_thread_finished(t, th, "upload")
            )
            thread.error.connect(
                lambda err, t=task, th=thread: self.__on_thread_error(t, th, err)
            )
            self.upload_threads.append(thread)
            thread.start()
            logger.debug("上传线程已启动: %s", file_name)

        return task

    def add_download_task(
        self, file_name, file_size, file_id, save_path, current_dir_id=0
    ):
        """添加下载任务"""
        task = DownloadTask(file_name, file_size, file_id, save_path, current_dir_id)
        self.download_tasks.append(task)
        logger.info(
            "添加下载任务: %s (%.2f MB, id=%s)",
            file_name,
            file_size / 1024 / 1024,
            file_id,
        )
        self.__update_download_table()

        if self.pan:
            thread = DownloadThread(task, self.pan)
            thread.progress_updated.connect(
                lambda progress, t=task: self.__update_task_progress(t, progress)
            )
            thread.status_updated.connect(
                lambda status, t=task: self.__update_task_status(t, status)
            )
            thread.finished.connect(
                lambda t=task, th=thread: self.__on_thread_finished(t, th, "download")
            )
            thread.error.connect(
                lambda err, t=task, th=thread: self.__on_thread_error(t, th, err)
            )
            self.download_threads.append(thread)
            thread.start()
            logger.debug("下载线程已启动: %s", file_name)

        return task

    def __update_task_progress(self, task, progress):
        """更新任务进度"""
        task.progress = progress
        if isinstance(task, UploadTask):
            self.__update_upload_table()
        elif isinstance(task, DownloadTask):
            self.__update_download_table()

    def __update_task_status(self, task, status):
        """更新任务状态"""
        task.status = status
        if isinstance(task, UploadTask):
            self.__update_upload_table()
        elif isinstance(task, DownloadTask):
            self.__update_download_table()

    def __on_thread_finished(self, task, thread, task_type):
        """线程完成回调：更新 UI 并清理线程资源。"""
        logger.info("任务完成: type=%s, name=%s", task_type, task.file_name)
        self.__cleanup_thread(thread, task_type)
        if task_type == "upload":
            self.__update_upload_table()
            InfoBar.success(
                title="上传完成",
                content=f"文件 '{task.file_name}' 上传成功",
                parent=self,
            )
        else:
            self.__update_download_table()

    def __on_thread_error(self, task, thread, error):
        """线程错误回调：更新 UI 并清理线程资源。"""
        logger.error(
            "任务失败: type=%s, name=%s, error=%s",
            type(task).__name__,
            task.file_name,
            error,
        )
        self.__cleanup_thread(thread, "upload" if isinstance(task, UploadTask) else "download")
        if isinstance(task, UploadTask):
            self.__update_upload_table()
        elif isinstance(task, DownloadTask):
            self.__update_download_table()

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
            thread.finished.disconnect()
        except TypeError:
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
            thread.wait(3000)

    def __remove_task(self, task, task_type):
        """删除任务及其关联线程。"""
        if task_type == "upload":
            if task in self.upload_tasks:
                self.upload_tasks.remove(task)
                # 查找并清理关联线程
                for t in list(self.upload_threads):
                    if t.task is task:
                        self.__cleanup_thread(t, "upload")
                        break
                self.__update_upload_table()
        else:
            if task in self.download_tasks:
                self.download_tasks.remove(task)
                # 查找并清理关联线程
                for t in list(self.download_threads):
                    if t.task is task:
                        self.__cleanup_thread(t, "download")
                        break
                self.__update_download_table()

    def __update_table(self, table, tasks, task_type):
        """更新传输表格（上传/下载共用）。

        只在行数变化时增删行；进度更新时仅刷新文字和进度条，
        不再重建操作按钮等重量级控件。
        """
        if table.rowCount() != len(tasks):
            table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            # ---- 文件名 ----
            name_item = table.item(row, 0)
            if not name_item:
                name_item = QTableWidgetItem(task.file_name)
                table.setItem(row, 0, name_item)
            else:
                name_item.setText(task.file_name)

            # ---- 文件大小 ----
            size_item = table.item(row, 1)
            if not size_item:
                size_item = QTableWidgetItem(format_file_size(task.file_size))
                table.setItem(row, 1, size_item)
            else:
                size_item.setText(format_file_size(task.file_size))

            # ---- 进度条 ----
            progress_bar = table.cellWidget(row, 2)
            if not progress_bar:
                progress_bar = ProgressBar()
                progress_bar.setTextVisible(False)
                table.setCellWidget(row, 2, progress_bar)
            progress_bar.setValue(task.progress)

            # ---- 百分比 ----
            percent_item = table.item(row, 3)
            if not percent_item:
                percent_item = QTableWidgetItem(f"{task.progress}%")
                percent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 3, percent_item)
            else:
                percent_item.setText(f"{task.progress}%")

            # ---- 状态 ----
            status_item = table.item(row, 4)
            if not status_item:
                status_item = QTableWidgetItem(task.status)
                table.setItem(row, 4, status_item)
            else:
                status_item.setText(task.status)

            # ---- 操作按钮（仅在行首次创建时构建，避免每 100ms 重建控件导致内存泄漏） ----
            if not table.cellWidget(row, 5):
                action_layout = QHBoxLayout()
                action_layout.setContentsMargins(0, 0, 0, 0)
                delete_button = PushButton(
                    FIF.DELETE.icon(), "删除任务", table
                )
                delete_button.setFixedSize(128, 24)
                delete_button.clicked.connect(
                    lambda _, t=task, tt=task_type: self.__remove_task(t, tt)
                )
                action_layout.addWidget(delete_button)
                action_widget = QWidget()
                action_widget.setLayout(action_layout)
                table.setCellWidget(row, 5, action_widget)

    def __update_upload_table(self):
        self.__update_table(self.uploadTable, self.upload_tasks, "upload")

    def __update_download_table(self):
        self.__update_table(self.downloadTable, self.download_tasks, "download")
