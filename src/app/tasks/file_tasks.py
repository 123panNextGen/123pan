from PyQt6.QtCore import QRunnable

from ..common.log import get_logger
from .signals import _LoadListSignals, _OpFinishedSignals, _StorageSignals

logger = get_logger(__name__)


class LoadListTask(QRunnable):
    def __init__(self, fetch_method, dir_id, signals: _LoadListSignals):
        super().__init__()
        self.fetch_method = fetch_method
        self.dir_id = dir_id
        self.signals = signals

    def run(self):
        try:
            file_items = self.fetch_method(self.dir_id)
            self.signals.finished.emit(file_items, "")
        except Exception as e:
            self.signals.finished.emit([], str(e))


class CreateFolderTask(QRunnable):
    def __init__(self, pan, folder_name, current_dir_id, signals, file_interface):
        super().__init__()
        self.pan = pan
        self.folder_name = folder_name
        self.current_dir_id = current_dir_id
        self.signals = signals
        self._fi = file_interface

    def run(self):
        try:
            current_parent_id = self.pan.parent_file_id
            self.pan.parent_file_id = self.current_dir_id
            result = self.pan.mkdir(self.folder_name)
            self.pan.parent_file_id = current_parent_id

            if result:
                items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
                self.signals.finished.emit(True, self.folder_name, "", "", items, folder_items)
            else:
                self.signals.finished.emit(False, self.folder_name, "", "", [], [])
        except Exception as e:
            self.signals.finished.emit(False, self.folder_name, "", str(e), [], [])


class DeleteFileTask(QRunnable):
    def __init__(self, pan, file_id, file_name, current_dir_id, signals, file_interface):
        super().__init__()
        self.pan = pan
        self.file_id = file_id
        self.file_name = file_name
        self.current_dir_id = current_dir_id
        self.signals = signals
        self._fi = file_interface

    def run(self):
        try:
            logger.info("删除文件: name=%s, id=%s", self.file_name, self.file_id)
            success = False
            for i, file in enumerate(self.pan.list):
                if str(file.get("FileId")) == str(self.file_id):
                    self.pan.delete_file(i, by_num=True, operation=True)
                    success = True
                    break

            if not success:
                logger.debug("文件未在当前列表中找到，尝试刷新目录")
                code, files = self.pan.get_dir_by_id(
                    self.current_dir_id, save=True, all=True, limit=1000
                )
                if code == 0:
                    for i, file in enumerate(self.pan.list):
                        if str(file.get("FileId")) == str(self.file_id):
                            self.pan.delete_file(i, by_num=True, operation=True)
                            success = True
                            break

            if success:
                logger.debug("删除成功: %s", self.file_name)
                items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
                self.signals.finished.emit(True, self.file_name, "", "", items, folder_items)
            else:
                logger.warning("删除失败: 文件未找到 %s", self.file_name)
                self.signals.finished.emit(False, self.file_name, "", "", [], [])
        except Exception as e:
            logger.error("删除异常: %s: %s", self.file_name, e)
            self.signals.finished.emit(False, self.file_name, "", str(e), [], [])


class RenameFileTask(QRunnable):
    def __init__(self, pan, file_id, old_name, new_name, current_dir_id, signals, file_interface):
        super().__init__()
        self.pan = pan
        self.file_id = file_id
        self.old_name = old_name
        self.new_name = new_name
        self.current_dir_id = current_dir_id
        self.signals = signals
        self._fi = file_interface

    def run(self):
        try:
            logger.info(
                "重命名文件: %s -> %s (id=%s)",
                self.old_name, self.new_name, self.file_id,
            )
            success = self.pan.rename_file(self.file_id, self.new_name)
            if success:
                logger.debug("重命名成功: %s -> %s", self.old_name, self.new_name)
                items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
                self.signals.finished.emit(True, self.old_name, self.new_name, "", items, folder_items)
            else:
                logger.warning("重命名失败: %s -> %s", self.old_name, self.new_name)
                self.signals.finished.emit(False, self.old_name, self.new_name, "重命名失败", [], [])
        except Exception as e:
            logger.error("重命名异常: %s: %s", self.old_name, e)
            self.signals.finished.emit(False, self.old_name, self.new_name, str(e), [], [])


class StorageTask(QRunnable):
    def __init__(self, file_interface, signals):
        super().__init__()
        self.file_interface = file_interface
        self.signals = signals

    def run(self):
        try:
            total_size = self.file_interface.calculate_total_storage(0)
            self.signals.finished.emit(total_size)
        except Exception as e:
            logger.error("统计存储信息时发生错误: %s", e)
            self.signals.finished.emit("0 B")
