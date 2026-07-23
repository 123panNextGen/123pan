"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import QRunnable

from ..common.log import get_logger
from .signals import _LoadListSignals

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


class BatchDeleteTask(QRunnable):
    """批量删除文件任务"""

    def __init__(self, pan, file_infos, current_dir_id, signals, file_interface):
        super().__init__()
        self.pan = pan
        self.file_infos = file_infos  # list of (file_id, file_name)
        self.current_dir_id = current_dir_id
        self.signals = signals
        self._fi = file_interface

    def run(self):
        try:
            names = [name for _, name in self.file_infos]
            logger.info("批量删除文件: %s", names)

            # 先获取完整文件列表
            code, files = self.pan.get_dir_by_id(
                self.current_dir_id, save=True, all=True, limit=1000
            )
            if code != 0:
                self.signals.finished.emit(False, "", "", "获取文件列表失败", [], [])
                return

            success_count = 0
            fail_count = 0
            last_error = ""

            for file_id, file_name in self.file_infos:
                try:
                    # 在 pan.list 中查找并删除
                    deleted = False
                    for i, file in enumerate(self.pan.list):
                        if str(file.get("FileId")) == str(file_id):
                            self.pan.delete_file(i, by_num=True, operation=True)
                            deleted = True
                            break

                    if deleted:
                        success_count += 1
                    else:
                        fail_count += 1
                        logger.warning("批量删除中未找到文件: %s (id=%s)", file_name, file_id)
                except Exception as e:
                    fail_count += 1
                    last_error = str(e)
                    logger.error("批量删除 %s 失败: %s", file_name, e)

            # 重新加载目录
            items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
            msg = f"成功 {success_count} 个"
            if fail_count > 0:
                msg += f"，失败 {fail_count} 个"
            self.signals.finished.emit(True, msg, "", last_error, items, folder_items)
        except Exception as e:
            logger.error("批量删除异常: %s", e)
            self.signals.finished.emit(False, "", "", str(e), [], [])
