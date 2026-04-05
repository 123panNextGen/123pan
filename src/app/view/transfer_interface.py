from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidgetItem,
    QFrame,
    QHBoxLayout,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QCoreApplication
from PyQt6.QtGui import QFont
from pathlib import Path
import requests

# 导入Pan123类
Pan123 = __import__("app.common.api").common.api.Pan123

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    TabBar,
    SegmentedWidget,
    TableWidget,
    PushButton,
    ProgressBar,
    InfoBar,
)

from ..common.style_sheet import StyleSheet
from ..common.api import format_file_size

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
    """上传线程"""

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
            # 更新状态为上传中
            self.status_updated.emit("上传中")

            # 保存当前目录
            current_parent_id = self.pan.parent_file_id

            # 设置目标目录
            self.pan.parent_file_id = self.task.target_dir_id

            # 执行上传
            self.pan.up_load(self.task.local_path)

            # 恢复当前目录
            self.pan.parent_file_id = current_parent_id

            # 更新状态为完成
            self.progress_updated.emit(100)
            self.status_updated.emit("已完成")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
            self.status_updated.emit("失败")


class DownloadThread(QThread):
    """下载线程"""

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
            # 更新状态为下载中
            self.status_updated.emit("下载中")

            # 记录调试信息
            from ..common.log import get_logger

            logger = get_logger(__name__)
            logger.debug(
                f"下载任务: {self.task.file_name}, file_id: {self.task.file_id}, type: {type(self.task.file_id)}"
            )
            logger.debug(f"当前目录ID: {self.task.current_dir_id}")

            # 直接使用文件ID下载，不需要查找索引
            # 先在当前文件夹中查找文件
            target_file = None

            # 尝试在当前目录中查找
            code, files = self.pan.get_dir_by_id(
                self.task.current_dir_id, save=False, all=True, limit=1000
            )
            if code == 0:
                logger.debug(
                    f"在当前目录中查找文件，当前目录ID: {self.task.current_dir_id}"
                )
                for file in files:
                    file_id = file.get("FileId")
                    if str(file_id) == str(self.task.file_id):
                        target_file = file
                        logger.debug(
                            f"在当前目录中找到文件: {target_file.get('FileName')}"
                        )
                        break

            # 如果还是找不到，尝试从Pan123的list属性中查找
            if not target_file:
                logger.debug("在当前目录中找不到文件，尝试从Pan123的list属性中查找")
                for file in self.pan.list:
                    file_id = file.get("FileId")
                    if str(file_id) == str(self.task.file_id):
                        target_file = file
                        logger.debug(
                            f"从Pan123的list属性中找到文件: {target_file.get('FileName')}"
                        )
                        break

            # 如果还是找不到，尝试获取根目录的所有文件，然后查找
            if not target_file:
                logger.debug("从Pan123的list属性中找不到文件，尝试获取根目录的所有文件")
                code, files = self.pan.get_dir_by_id(
                    0, save=False, all=True, limit=1000
                )
                if code == 0:
                    for file in files:
                        file_id = file.get("FileId")
                        if str(file_id) == str(self.task.file_id):
                            target_file = file
                            logger.debug(
                                f"从根目录的所有文件中找到文件: {target_file.get('FileName')}"
                            )
                            break

            if not target_file:
                # 如果还是找不到，尝试直接使用文件ID构造文件详情
                logger.debug("所有搜索方法都找不到文件，尝试直接使用文件ID构造文件详情")
                # 这里我们尝试直接使用文件ID获取文件详情
                # 注意：这种方法可能不适用，因为link_by_fileDetail需要完整的文件详情
                # 但我们可以尝试构造一个基本的文件详情对象
                target_file = {
                    "FileId": self.task.file_id,
                    "FileName": self.task.file_name,
                    "Type": 0,  # 假设是文件
                    "Size": self.task.file_size,
                    "Etag": "",  # 空ETag
                    "S3KeyFlag": False,  # 假设不是S3存储
                }
                logger.debug(f"构造文件详情: {target_file}")

            # 执行下载
            class ProgressSignals:
                def __init__(self, thread):
                    self.thread = thread

                def emit(self, value):
                    self.thread.progress_updated.emit(value)

            signals = ProgressSignals(self)

            # 使用文件详情获取下载链接
            logger.debug(f"开始下载文件: {target_file.get('FileName')}")
            download_url = self.pan.link_by_fileDetail(target_file, showlink=False)
            if isinstance(download_url, int):
                logger.error(f"获取下载链接失败，返回码: {download_url}")
                raise RuntimeError(f"获取下载链接失败，返回码: {download_url}")

            # 直接从URL下载
            self.__download_from_url(
                download_url, self.task.save_path, self.task.file_name, signals
            )

            # 更新状态为完成
            self.progress_updated.emit(100)
            self.status_updated.emit("已完成")
            self.finished.emit()
        except Exception as e:
            logger.error(f"下载错误: {e}")
            self.error.emit(str(e))
            self.status_updated.emit("失败")

    def __download_from_url(self, url, save_path, file_name, signals):
        """从URL下载文件"""

        # 确保保存路径存在
        file_path = Path(save_path)
        save_dir = file_path.parent
        if not save_dir.exists():
            save_dir.mkdir(parents=True, exist_ok=True)

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")

        # 发送请求
        logger.debug(f"下载URL: {url}")
        try:
            with requests.get(url, stream=True, timeout=30) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded_size = 0
                last_progress = 0

                # 写入文件
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                progress = int(downloaded_size * 100 / total_size)
                                # 只在进度变化时发送信号，减少信号发射频率
                                if progress != last_progress:
                                    signals.emit(progress)
                                    last_progress = progress

            # 重命名临时文件
            if temp_path.exists():
                if file_path.exists():
                    file_path.unlink()
                temp_path.rename(file_path)
            else:
                raise Exception("临时文件不存在")
        except requests.exceptions.RequestException as e:
            logger.error(f"下载请求失败: {url} -> {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"下载请求失败: {e}")
        except Exception as e:
            # 清理临时文件
            if temp_path.exists():
                temp_path.unlink()
            raise e


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
        self.__update_upload_table()

        # 启动上传线程
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

        return task

    def add_download_task(
        self, file_name, file_size, file_id, save_path, current_dir_id=0
    ):
        """添加下载任务"""
        task = DownloadTask(file_name, file_size, file_id, save_path, current_dir_id)
        self.download_tasks.append(task)
        self.__update_download_table()

        # 启动下载线程
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

        return task

    def __update_task_progress(self, task, progress):
        """更新任务进度"""
        task.progress = progress
        # 使用QCoreApplication.processEvents()来确保界面响应

        QCoreApplication.processEvents()
        if isinstance(task, UploadTask):
            self.__update_upload_table()
        elif isinstance(task, DownloadTask):
            self.__update_download_table()

    def __update_task_status(self, task, status):
        """更新任务状态"""
        task.status = status
        # 使用QCoreApplication.processEvents()来确保界面响应

        QCoreApplication.processEvents()
        if isinstance(task, UploadTask):
            self.__update_upload_table()
        elif isinstance(task, DownloadTask):
            self.__update_download_table()

    def __task_finished(self, task, task_type):
        """任务完成处理"""
        if task_type == "upload":
            self.__update_upload_table()
            # 上传完成时显示右上角提示
            InfoBar.success(
                title="上传完成",
                content=f"文件 '{task.file_name}' 上传成功",
                parent=self,
            )
        else:
            self.__update_download_table()

    def __task_error(self, task, error):
        """任务错误处理"""
        logger.error(f"任务错误: {error}")
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

    def __update_upload_table(self):
        """更新上传表格"""
        # 确保表格行数正确
        if self.uploadTable.rowCount() != len(self.upload_tasks):
            self.uploadTable.setRowCount(len(self.upload_tasks))

        for row, task in enumerate(self.upload_tasks):
            # 文件名
            name_item = self.uploadTable.item(row, 0)
            if not name_item:
                name_item = QTableWidgetItem(task.file_name)
                self.uploadTable.setItem(row, 0, name_item)
            else:
                name_item.setText(task.file_name)

            # 文件大小
            size_item = self.uploadTable.item(row, 1)
            if not size_item:
                size_item = QTableWidgetItem(format_file_size(task.file_size))
                self.uploadTable.setItem(row, 1, size_item)

            # 进度条
            progress_bar = self.uploadTable.cellWidget(row, 2)
            if not progress_bar:
                progress_bar = ProgressBar()
                progress_bar.setTextVisible(False)  # 不显示百分比，因为我们在旁边显示
                self.uploadTable.setCellWidget(row, 2, progress_bar)
            progress_bar.setValue(task.progress)

            # 百分比
            percent_item = self.uploadTable.item(row, 3)
            if not percent_item:
                percent_item = QTableWidgetItem(f"{task.progress}%")
                percent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.uploadTable.setItem(row, 3, percent_item)
            else:
                percent_item.setText(f"{task.progress}%")

            # 状态
            status_item = self.uploadTable.item(row, 4)
            if not status_item:
                status_item = QTableWidgetItem(task.status)
                self.uploadTable.setItem(row, 4, status_item)
            else:
                status_item.setText(task.status)

            # 操作按钮 - 只在首次创建时添加
            if not self.uploadTable.cellWidget(row, 5):
                action_layout = QHBoxLayout()
                delete_button = PushButton(
                    FIF.DELETE.icon(), "删除任务", self.uploadTable
                )
                delete_button.setFixedSize(128, 24)

                # 添加点击事件
                delete_button.clicked.connect(
                    lambda _, t=task: self.__remove_task(t, "upload")
                )

                action_layout.addWidget(delete_button)

                action_widget = QWidget()
                action_widget.setLayout(action_layout)
                self.uploadTable.setCellWidget(row, 5, action_widget)

    def __update_download_table(self):
        """更新下载表格"""
        # 确保表格行数正确
        if self.downloadTable.rowCount() != len(self.download_tasks):
            self.downloadTable.setRowCount(len(self.download_tasks))

        for row, task in enumerate(self.download_tasks):
            # 文件名
            name_item = self.downloadTable.item(row, 0)
            if not name_item:
                name_item = QTableWidgetItem(task.file_name)
                self.downloadTable.setItem(row, 0, name_item)
            else:
                name_item.setText(task.file_name)

            # 文件大小
            size_item = self.downloadTable.item(row, 1)
            if not size_item:
                size_item = QTableWidgetItem(format_file_size(task.file_size))
                self.downloadTable.setItem(row, 1, size_item)

            # 进度条
            progress_bar = self.downloadTable.cellWidget(row, 2)
            if not progress_bar:
                progress_bar = ProgressBar()
                progress_bar.setTextVisible(False)  # 不显示百分比，因为我们在旁边显示
                self.downloadTable.setCellWidget(row, 2, progress_bar)
            progress_bar.setValue(task.progress)

            # 百分比
            percent_item = self.downloadTable.item(row, 3)
            if not percent_item:
                percent_item = QTableWidgetItem(f"{task.progress}%")
                percent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.downloadTable.setItem(row, 3, percent_item)
            else:
                percent_item.setText(f"{task.progress}%")

            # 状态
            status_item = self.downloadTable.item(row, 4)
            if not status_item:
                status_item = QTableWidgetItem(task.status)
                self.downloadTable.setItem(row, 4, status_item)
            else:
                status_item.setText(task.status)

            # 操作按钮 - 只在首次创建时添加
            if not self.downloadTable.cellWidget(row, 5):
                action_layout = QHBoxLayout()
                delete_button = PushButton(
                    FIF.DELETE.icon(), "删除任务", self.downloadTable
                )
                delete_button.setFixedSize(128, 24)

                # 添加点击事件
                delete_button.clicked.connect(
                    lambda _, t=task: self.__remove_task(t, "download")
                )

                action_layout.addWidget(delete_button)

                action_widget = QWidget()
                action_widget.setLayout(action_layout)
                self.downloadTable.setCellWidget(row, 5, action_widget)
