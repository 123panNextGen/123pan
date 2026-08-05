"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import QRunnable

from ..common.api import Pan123
from ..common.log import get_logger
from .signals import (
    _AutoLoginSignals,
    _DeviceListSignals,
    _FolderListSignals,
    _LoadListSignals,
    _ShareListSignals,
    _StorageInfoSignals,
    _TrashListSignals,
    _UserInfoSignals,
)

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


class LoadStorageInfoTask(QRunnable):
    """后台加载云盘空间信息，避免主线程网络请求阻塞 GUI。"""

    def __init__(self, pan, signals: _StorageInfoSignals):
        super().__init__()
        self.pan = pan
        self.signals = signals

    def run(self):
        try:
            result = self.pan.get_user_info()
            if result.code != 0 or result.data is None:
                self.signals.finished.emit(None, "获取用户信息失败")
            else:
                self.signals.finished.emit(result.data, "")
        except Exception as e:
            logger.error("获取用户信息失败: %s", e)
            self.signals.finished.emit(None, str(e))


class LoadTrashListTask(QRunnable):
    """后台加载回收站列表，避免主线程网络请求阻塞 GUI。"""

    def __init__(self, pan, signals: _TrashListSignals):
        super().__init__()
        self.pan = pan
        self.signals = signals

    def run(self):
        try:
            items = self.pan._file.recycle()
            self.signals.finished.emit(items, "")
        except Exception as e:
            logger.error("获取回收站列表失败: %s", e)
            self.signals.finished.emit([], str(e))


class LoadShareListsTask(QRunnable):
    """后台加载免费/付费分享列表。"""

    def __init__(self, pan, signals: _ShareListSignals):
        super().__init__()
        self.pan = pan
        self.signals = signals

    def run(self):
        try:
            free_resp = self.pan.get_free_share_list()
            pay_resp = self.pan.get_pay_share_list()

            if free_resp.code == 0 and free_resp.data is not None:
                free_data, free_err = free_resp.data.data, ""
            else:
                free_data, free_err = None, free_resp.msg or "获取免费分享列表失败"

            if pay_resp.code == 0 and pay_resp.data is not None:
                pay_data, pay_err = pay_resp.data.data, ""
            else:
                pay_data, pay_err = None, pay_resp.msg or "获取付费分享列表失败"

            self.signals.finished.emit(free_data, free_err, pay_data, pay_err)
        except Exception as e:
            logger.error("获取分享列表失败: %s", e)
            self.signals.finished.emit(None, str(e), None, str(e))


class LoadUserInfoTask(QRunnable):
    """后台加载云盘用户信息。"""

    def __init__(self, pan, signals: _UserInfoSignals):
        super().__init__()
        self.pan = pan
        self.signals = signals

    def run(self):
        try:
            result = self.pan.get_user_info()
            if result.code == 0 and result.data is not None:
                self.signals.finished.emit(result.data, "")
            else:
                self.signals.finished.emit(None, result.msg or "获取用户信息失败")
        except Exception as e:
            logger.error("获取用户信息失败: %s", e)
            self.signals.finished.emit(None, str(e))


class LoadDeviceListTask(QRunnable):
    """后台加载登录设备列表。"""

    def __init__(self, pan, signals: _DeviceListSignals):
        super().__init__()
        self.pan = pan
        self.signals = signals

    def run(self):
        try:
            result = self.pan.get_device_list()
            if result.code == 0 and result.data is not None:
                self.signals.finished.emit(result.data, "")
            else:
                self.signals.finished.emit(None, result.msg or "获取设备列表失败")
        except Exception as e:
            logger.error("获取设备列表失败: %s", e)
            self.signals.finished.emit(None, str(e))


class LoadFolderListTask(QRunnable):
    """后台加载指定目录下的子文件夹列表（懒加载目录树用）。"""

    def __init__(self, pan, dir_id, signals: _FolderListSignals):
        super().__init__()
        self.pan = pan
        self.dir_id = dir_id
        self.signals = signals

    def run(self):
        try:
            cached_state = (
                self.pan.file_page,
                self.pan.total,
                self.pan.all_file,
            )
            self.pan.file_page = 0
            try:
                code, items = self.pan.get_dir_by_id(
                    self.dir_id, save=False, all=True, limit=100
                )
                if code != 0:
                    self.signals.finished.emit(self.dir_id, [], "获取目录失败")
                    return
                folders = [
                    i for i in items if int(i.get("Type", 0)) == 1
                ]
                self.signals.finished.emit(self.dir_id, folders, "")
            finally:
                self.pan.file_page, self.pan.total, self.pan.all_file = cached_state
        except Exception as e:
            logger.error("加载目录失败: dir_id=%s, err=%s", self.dir_id, e)
            self.signals.finished.emit(self.dir_id, [], str(e))


class AutoLoginTask(QRunnable):
    """后台自动登录：构造 Pan123 并校验 get_dir，避免启动时阻塞主线程。

    Pan123 构造器内部会进行网络请求（get_dir / login），
    在后台线程完成后再通过信号回到主线程继续登录流程。
    """

    def __init__(self, signals: _AutoLoginSignals):
        super().__init__()
        self.signals = signals

    def run(self):
        pan = None
        try:
            pan = Pan123(readfile=True, input_pwd=False)
            res_code = pan.get_dir(save=False)[0]
            if res_code == 0:
                self.signals.finished.emit(pan, "")
            else:
                logger.warning("自动登录失败: get_dir 返回 code=%s", res_code)
                pan.close()
                self.signals.finished.emit(None, f"get_dir 返回 code={res_code}")
        except Exception as e:
            if pan is not None:
                pan.close()
            logger.warning("自动登录异常: %s", e)
            self.signals.finished.emit(None, str(e))


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


class MoveFileTask(QRunnable):
    """移动文件/文件夹任务"""

    def __init__(self, pan, file_infos, target_parent_id, current_dir_id, signals, file_interface):
        super().__init__()
        self.pan = pan
        self.file_infos = file_infos  # list of (file_id, file_name)
        self.target_parent_id = target_parent_id
        self.current_dir_id = current_dir_id
        self.signals = signals
        self._fi = file_interface

    def run(self):
        try:
            file_ids = [fid for fid, _ in self.file_infos]
            names = [name for _, name in self.file_infos]
            logger.info("移动文件: %s -> 目录 %s", names, self.target_parent_id)
            success, msg = self.pan.move_file(file_ids, self.target_parent_id)
            if success:
                items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
                self.signals.finished.emit(
                    True, "移动成功", "", "", items, folder_items
                )
            else:
                logger.warning("移动失败: %s", msg)
                self.signals.finished.emit(False, "移动失败", "", msg, [], [])
        except Exception as e:
            logger.error("移动异常: %s", e)
            self.signals.finished.emit(False, "移动失败", "", str(e), [], [])


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
