from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidgetItem,
    QFrame,
    QHBoxLayout,
)
import time

from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
from ..common.api import format_file_size
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
    """上传线程（支持速度限制）"""

    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task, pan):
        super().__init__()
        self.task = task
        self.pan = pan

    def run(self):
        try:
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

            self.progress_updated.emit(100)
            self.status_updated.emit("已完成")
            self.finished.emit()
            logger.info("上传完成: %s (%.1fs)", self.task.file_name, elapsed)
        except Exception as e:
            logger.error("上传失败: %s: %s", self.task.file_name, e)
            self.error.emit(str(e))
            self.status_updated.emit("失败")


class DownloadThread(QThread):
    """下载线程（支持多线程分片和速度限制）"""

    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task, pan):
        super().__init__()
        self.task = task
        self.pan = pan

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
                "下载配置: multi_thread=%s, speed_limit=%d KB/s", multi_thread, dl_limit
            )

            self.pan.set_download_multi_thread(multi_thread)
            self.pan.set_download_speed_limit(dl_limit)

            def _on_progress(downloaded, total):
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
                "下载失败: %s: %s:%s", self.task.file_name, type(e).__name__, e
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
                    logger.debug(f"在当前目录中找到: {f.get('FileName')}")
                    return f

        # 从 Pan123 list 中查找
        for f in self.pan.list:
            if str(f.get("FileId")) == str(self.task.file_id):
                logger.debug(f"从 list 中找到: {f.get('FileName')}")
                return f

        # 从根目录查找
        code, files = self.pan.get_dir_by_id(0, save=False, all=True, limit=1000)
        if code == 0:
            for f in files:
                if str(f.get("FileId")) == str(self.task.file_id):
                    logger.debug(f"从根目录找到: {f.get('FileName')}")
                    return f

        return None


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
            thread.finished.connect(lambda: self.__task_finished(task, "upload"))
            thread.error.connect(lambda error, t=task: self.__task_error(t, error))
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
            thread.finished.connect(lambda: self.__task_finished(task, "download"))
            thread.error.connect(lambda error, t=task: self.__task_error(t, error))
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

    def __task_finished(self, task, task_type):
        """任务完成处理"""
        logger.info("任务完成: type=%s, name=%s", task_type, task.file_name)
        if task_type == "upload":
            self.__update_upload_table()
            InfoBar.success(
                title="上传完成",
                content=f"文件 '{task.file_name}' 上传成功",
                parent=self,
            )
        else:
            self.__update_download_table()

    def __task_error(self, task, error):
        """任务错误处理"""
        logger.error(
            "任务失败: type=%s, name=%s, error=%s",
            type(task).__name__,
            task.file_name,
            error,
        )
        if isinstance(task, UploadTask):
            self.__update_upload_table()
        elif isinstance(task, DownloadTask):
            self.__update_download_table()

    def __remove_task(self, task, task_type):
        """删除任务"""
        if task_type == "upload":
            if task in self.upload_tasks:
                self.upload_tasks.remove(task)
                self.__update_upload_table()
        else:
            if task in self.download_tasks:
                self.download_tasks.remove(task)
                self.__update_download_table()

    def __update_table(self, table, tasks, task_type):
        """更新传输表格（上传/下载共用）"""
        if table.rowCount() != len(tasks):
            table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            name_item = table.item(row, 0)
            if not name_item:
                name_item = QTableWidgetItem(task.file_name)
                table.setItem(row, 0, name_item)
            else:
                name_item.setText(task.file_name)

            size_item = table.item(row, 1)
            if not size_item:
                size_item = QTableWidgetItem(format_file_size(task.file_size))
                table.setItem(row, 1, size_item)
            else:
                size_item.setText(format_file_size(task.file_size))

            progress_bar = table.cellWidget(row, 2)
            if not progress_bar:
                progress_bar = ProgressBar()
                progress_bar.setTextVisible(False)
                table.setCellWidget(row, 2, progress_bar)
            progress_bar.setValue(task.progress)

            percent_item = table.item(row, 3)
            if not percent_item:
                percent_item = QTableWidgetItem(f"{task.progress}%")
                percent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 3, percent_item)
            else:
                percent_item.setText(f"{task.progress}%")

            status_item = table.item(row, 4)
            if not status_item:
                status_item = QTableWidgetItem(task.status)
                table.setItem(row, 4, status_item)
            else:
                status_item.setText(task.status)

            if not table.cellWidget(row, 5):
                action_layout = QHBoxLayout()
                delete_button = PushButton(
                    FIF.DELETE.icon(), "删除任务", table
                )
                delete_button.setFixedSize(128, 24)
                delete_button.clicked.connect(
                    lambda _, t=task: self.__remove_task(t, task_type)
                )
                action_layout.addWidget(delete_button)
                action_widget = QWidget()
                action_widget.setLayout(action_layout)
                table.setCellWidget(row, 5, action_widget)

    def __update_upload_table(self):
        self.__update_table(self.uploadTable, self.upload_tasks, "upload")

    def __update_download_table(self):
        self.__update_table(self.downloadTable, self.download_tasks, "download")
