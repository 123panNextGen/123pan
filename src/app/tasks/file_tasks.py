"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import QRunnable

from ..common.api import Pan123
from ..common.config import ConfigManager
from ..common.log import get_logger
from ..service.offline_service import OfflineService
from .signals import (
    _AutoLoginSignals,
    _CheckVersionSignals,
    _DeleteSharesSignals,
    _DeviceListSignals,
    _DownloadLinkSignals,
    _FolderListSignals,
    _GenerateRapidSignals,
    _LoadListSignals,
    _OfflineResolveSignals,
    _OfflineSubmitSignals,
    _PasswordLoginSignals,
    _RapidTransferSignals,
    _ShareCreateSignals,
    _ShareListSignals,
    _StorageInfoSignals,
    _TrashListSignals,
    _TrashOpSignals,
    _UploadFolderSignals,
    _UserInfoSignals,
)

logger = get_logger(__name__)


def track_task(widget, task):
    """持有后台任务引用，防止任务/信号在工作线程运行期间被 GC 回收。

    背景：QRunnable 若不被 Python 侧持有引用，GC 可能在 worker 线程
    仍运行 run() 时回收其包装对象（连带回收信号对象），导致
    'wrapped C/C++ object has been deleted' 的 RuntimeError。
    界面需在 __init__ 中初始化 `self._pending_tasks = []`。
    """
    widget._pending_tasks.append(task)


def release_task(widget, task):
    """任务完成后释放引用。"""
    try:
        widget._pending_tasks.remove(task)
    except ValueError:
        pass


def connect_tracked(widget, signals, signal_name, slot, task):
    """连接信号并追踪任务引用，回调执行后自动释放。"""
    def _wrapper(*args, t=task, s=slot):
        s(*args)
        release_task(widget, t)

    getattr(signals, signal_name).connect(_wrapper)
    track_task(widget, task)


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


class CheckVersionTask(QRunnable):
    """后台检查 GitHub 最新版本。"""

    def __init__(self, signals: _CheckVersionSignals):
        super().__init__()
        self.signals = signals

    def run(self):
        try:
            from ..common.api import check_version

            self.signals.finished.emit(check_version())
        except Exception as e:
            logger.error("检查版本失败: %s", e)
            self.signals.finished.emit(False)


class PasswordLoginTask(QRunnable):
    """后台执行密码登录（构造 Pan123 + login），避免阻塞登录对话框。"""

    def __init__(self, user_name, password, signals: _PasswordLoginSignals):
        super().__init__()
        self.user_name = user_name
        self.password = password
        self.signals = signals

    def run(self):
        pan = None
        try:
            account = ConfigManager.get_account(self.user_name)
            if account:
                logger.debug("使用已保存账号信息登录: %s", self.user_name)
                pan = Pan123(readfile=True, user_name=self.user_name, password=self.password)
            else:
                logger.debug("新账号登录: %s", self.user_name)
                pan = Pan123(readfile=False, user_name=self.user_name, password=self.password)

            code = pan.login()
            self.signals.finished.emit(pan, code, "")
        except Exception as e:
            if pan is not None:
                pan.close()
            logger.error("登录异常: %s", e)
            self.signals.finished.emit(None, -1, str(e))


class DeleteSharesTask(QRunnable):
    """后台批量删除分享链接。"""

    def __init__(self, pan, share_ids, signals: _DeleteSharesSignals):
        super().__init__()
        self.pan = pan
        self.share_ids = share_ids
        self.signals = signals

    def run(self):
        success_count = 0
        fail_count = 0
        last_error = ""
        for share_id in self.share_ids:
            try:
                result = self.pan.delete_share(share_id)
                if result.code == 0:
                    success_count += 1
                else:
                    fail_count += 1
                    last_error = result.msg
                    logger.warning(
                        "分享删除失败 (shareId=%s), msg=%s", share_id, result.msg
                    )
            except Exception as e:
                fail_count += 1
                last_error = str(e)
                logger.error("分享删除异常 (shareId=%s): %s", share_id, e)
        logger.info("分享删除完成: 成功 %d, 失败 %d", success_count, fail_count)
        self.signals.finished.emit(success_count, fail_count, last_error)


class RestoreTrashTask(QRunnable):
    """后台恢复回收站文件。"""

    def __init__(self, pan, trash_items, selected, signals: _TrashOpSignals):
        super().__init__()
        self.pan = pan
        self.trash_items = trash_items
        self.selected = selected
        self.signals = signals

    def run(self):
        try:
            for file_info in self.selected:
                self.pan._file.delete_file(
                    self.trash_items, file_info, by_num=False, operation=False
                )
            self.signals.finished.emit(True, "")
        except Exception as e:
            logger.error("恢复文件失败: %s", e)
            self.signals.finished.emit(False, str(e))


class PermDeleteTrashTask(QRunnable):
    """后台永久删除回收站文件。"""

    def __init__(self, pan, file_ids, signals: _TrashOpSignals):
        super().__init__()
        self.pan = pan
        self.file_ids = file_ids
        self.signals = signals

    def run(self):
        try:
            success, msg = self.pan._file.permanent_delete_files(self.file_ids)
            self.signals.finished.emit(success, msg)
        except Exception as e:
            logger.error("永久删除失败: %s", e)
            self.signals.finished.emit(False, str(e))


class GetDownloadLinkTask(QRunnable):
    """后台获取文件下载链接。"""

    def __init__(self, pan, file_detail, signals: _DownloadLinkSignals):
        super().__init__()
        self.pan = pan
        self.file_detail = file_detail
        self.signals = signals

    def run(self):
        try:
            url = self.pan.link_by_fileDetail(self.file_detail, showlink=False)
            if isinstance(url, str) and url:
                self.signals.finished.emit(url, "")
            else:
                self.signals.finished.emit("", f"获取下载链接失败 (code={url})")
        except Exception as e:
            logger.error("获取下载链接失败: %s", e)
            self.signals.finished.emit("", str(e))


class CreateShareTask(QRunnable):
    """后台创建分享链接。"""

    def __init__(self, pan, file_id, share_pwd, signals: _ShareCreateSignals):
        super().__init__()
        self.pan = pan
        self.file_id = file_id
        self.share_pwd = share_pwd
        self.signals = signals

    def run(self):
        try:
            share_url = self.pan.share(
                [self.file_id], share_pwd=self.share_pwd or ""
            )
            if isinstance(share_url, str) and share_url:
                self.signals.finished.emit(share_url, "")
            else:
                self.signals.finished.emit("", "生成分享链接失败")
        except Exception as e:
            logger.error("生成分享链接失败: %s", e)
            self.signals.finished.emit("", str(e))


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

class CopyFileTask(QRunnable):
    """复制文件/文件夹到目标目录（支持一次复制到多个目标目录）"""

    def __init__(self, pan, file_infos, target_parent_ids, current_dir_id, signals, file_interface):
        super().__init__()
        self.pan = pan
        self.file_infos = file_infos  # list of (file_id, file_name)
        self.target_parent_ids = target_parent_ids
        self.current_dir_id = current_dir_id
        self.signals = signals
        self._fi = file_interface

    @staticmethod
    def _normalize_targets(target_parent_ids):
        """统一为去重后的目标目录 ID 列表（兼容单个 int / 列表 / 元组）。"""
        if isinstance(target_parent_ids, (list, tuple, set)):
            targets = (int(t) for t in target_parent_ids if t is not None)
        else:
            targets = (int(target_parent_ids),)
        return list(dict.fromkeys(targets))

    def run(self):
        try:
            file_ids = [fid for fid, _ in self.file_infos]
            names = [name for _, name in self.file_infos]
            targets = self._normalize_targets(self.target_parent_ids)
            if not targets:
                logger.warning("复制文件: 未选择目标目录")
                self.signals.finished.emit(False, "复制失败", "", "未选择目标目录", [], [])
                return

            ok_targets = []
            failures = []  # list of (target, err_msg)
            for target in targets:
                try:
                    logger.info("复制文件: %s -> 目录 %s", names, target)
                    success, msg = self.pan.copy_file(
                        file_ids, target, source_parent_id=self.current_dir_id,
                    )
                    if success:
                        ok_targets.append(target)
                    else:
                        failures.append((target, msg))
                except Exception as e:
                    logger.error("复制异常: target=%s, %s", target, e)
                    failures.append((target, str(e)))

            if failures:
                if len(targets) == 1:
                    detail = failures[0][1] or "复制失败"
                else:
                    detail = "；".join(
                        f"目录#{t}: {m}" for t, m in failures
                    )
                if ok_targets:
                    # 部分目标成功：刷新列表，并回传失败明细（success=True + error 供 UI 提示）
                    items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
                    self.signals.finished.emit(True, "复制成功", "", detail, items, folder_items)
                    return
                logger.warning("复制失败: %s", detail)
                self.signals.finished.emit(False, "复制失败", "", detail, [], [])
                return

            items, folder_items = self._fi._reload_dir_data(self.current_dir_id)
            self.signals.finished.emit(True, "复制成功", "", "", items, folder_items)
        except Exception as e:
            logger.error("复制异常: %s", e)
            self.signals.finished.emit(False, "复制失败", "", str(e), [], [])

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


class UploadFolderTask(QRunnable):
    """文件夹上传：递归遍历本地目录，在云端创建对应目录结构。

    完成后通过信号返回待上传文件列表 [(local_path, cloud_dir_id), ...]，
    由界面层逐一加入上传队列。同名云端文件夹存在时复用（合并），
    避免重复创建目录。
    """

    def __init__(self, pan, local_root, target_dir_id, signals: _UploadFolderSignals):
        super().__init__()
        self.pan = pan
        self.local_root = local_root
        self.target_dir_id = int(target_dir_id)
        self.signals = signals
        # 任务内已知目录缓存：(parent_id, name) -> file_id，避免重复建目录
        self._known_dirs = {}

    def run(self):
        try:
            files = self._walk_and_make_dirs()
            logger.info(
                "文件夹上传扫描完成: %s, %d 个文件", self.local_root, len(files)
            )
            self.signals.finished.emit(files, "")
        except Exception as e:
            logger.error("文件夹上传失败: %s (%s)", self.local_root, e)
            self.signals.finished.emit([], str(e))

    def _walk_and_make_dirs(self):
        """遍历本地目录并创建云端目录结构。

        Returns:
            [(local_path, cloud_dir_id), ...] 待上传文件列表
        """
        import os as _os
        from pathlib import Path as _Path

        root = _Path(self.local_root)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"文件夹不存在: {self.local_root}")

        # 顶层文件夹（以本地文件夹名命名）在目标目录中创建/复用
        top_id = self._ensure_folder(root.name, self.target_dir_id)
        if top_id is None:
            raise RuntimeError("创建云端顶层文件夹失败")

        files = []
        for dirpath, dirnames, filenames in _os.walk(root):
            rel = _os.path.relpath(dirpath, root)
            parent_cloud_id = top_id
            if rel != ".":
                # 递归创建/复用子目录
                for part in rel.split(_os.sep):
                    parent_cloud_id = self._ensure_folder(part, parent_cloud_id)
                    if parent_cloud_id is None:
                        raise RuntimeError(f"创建云端子文件夹失败: {part}")
            for fname in filenames:
                full = _Path(dirpath) / fname
                if not full.is_file():
                    continue
                files.append((str(full), parent_cloud_id))
        return files

    def _ensure_folder(self, name, parent_id):
        """在 parent_id 下查找同名文件夹，不存在则创建。

        Returns:
            int: 云端文件夹 FileId；失败返回 None
        """
        key = (parent_id, name)
        if key in self._known_dirs:
            return self._known_dirs[key]

        # 先查找目标目录下是否已有同名文件夹（合并上传）
        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
        self.pan.file_page = 0
        try:
            code, items = self.pan.get_dir_by_id(
                parent_id, save=False, all=True, limit=100
            )
            if code == 0:
                for item in items:
                    if int(item.get("Type", 0)) == 1 and item.get("FileName") == name:
                        fid = int(item["FileId"])
                        self._known_dirs[key] = fid
                        return fid
        finally:
            self.pan.file_page, self.pan.total, self.pan.all_file = cached_state

        # 不存在则创建
        fid, err = self.pan.create_folder(name, parent_id)
        if fid is None:
            logger.error("创建云端文件夹失败: %s (%s)", name, err)
            return None
        fid = int(fid)
        self._known_dirs[key] = fid
        return fid


class OfflineResolveTask(QRunnable):
    """后台解析离线下载链接。"""

    def __init__(self, pan, urls, signals: _OfflineResolveSignals):
        super().__init__()
        self.pan = pan
        self.urls = urls
        self.signals = signals

    def run(self):
        try:
            resources = self.pan.offline_resolve(self.urls)
            self.signals.finished.emit(resources, "")
        except Exception as e:
            logger.error("离线下载解析失败: %s", e)
            self.signals.finished.emit([], str(e))


class OfflineSubmitTask(QRunnable):
    """后台提交离线下载任务。"""

    def __init__(self, pan, resources, signals: _OfflineSubmitSignals):
        super().__init__()
        self.pan = pan
        self.resources = resources
        self.signals = signals

    def run(self):
        try:
            task_list = self.pan.offline_submit(self.resources)
            self.signals.finished.emit(task_list, "")
        except Exception as e:
            logger.error("离线下载提交失败: %s", e)
            self.signals.finished.emit([], str(e))


class RapidTransferTask(QRunnable):
    """后台执行秒传导入（建目录 + 逐个秒传）。"""

    def __init__(self, pan, files, parent_dir_id, signals: _RapidTransferSignals):
        super().__init__()
        self.pan = pan
        self.files = files
        self.parent_dir_id = parent_dir_id
        self.signals = signals

    def run(self):
        try:
            total = len(self.files)

            def _on_progress(current, total_count):
                self.signals.progress.emit(current, total_count)

            stats = self.pan.offline_rapid_transfer(
                self.files, self.parent_dir_id,
                progress_callback=_on_progress,
            )
            self.signals.finished.emit(stats, "")
        except Exception as e:
            logger.error("秒传导入失败: %s", e)
            self.signals.finished.emit({}, str(e))


class GenerateRapidTask(QRunnable):
    """后台生成秒传数据（JSON + 文本链接）。

    对选中的文件/文件夹递归收集 etag/size/path，生成标准秒传格式。
    """

    def __init__(self, pan, file_infos, signals: _GenerateRapidSignals):
        super().__init__()
        self.pan = pan
        # file_infos: [(item_dict, rel_path), ...]，rel_path 从当前目录起
        self.file_infos = file_infos
        self.signals = signals

    def run(self):
        try:
            files = self._collect_files()
            if not files:
                self.signals.finished.emit("", "", 0, 0, "没有可生成的文件")
                return
            json_text, link_text = self.pan.offline_build_rapid(files)
            total_size = sum(int(f.get("size", 0) or 0) for f in files)
            self.signals.finished.emit(
                json_text, link_text, len(files), total_size, ""
            )
        except Exception as e:
            logger.error("生成秒传数据失败: %s", e)
            self.signals.finished.emit("", "", 0, 0, str(e))

    def _collect_files(self):
        """递归收集文件（etag/size/path）。"""
        result = []
        for item, rel_path in self.file_infos:
            if int(item.get("Type", 0)) == 1:
                self._collect_folder(int(item["FileId"]), rel_path, result)
            else:
                etag = str(item.get("Etag", "") or "").lower()
                if OfflineService._is_valid_etag(etag):
                    result.append({
                        "path": rel_path,
                        "etag": etag,
                        "size": int(item.get("Size", 0) or 0),
                    })
        return result

    def _collect_folder(self, folder_id, rel_path, result):
        """递归收集文件夹下所有文件。"""
        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
        self.pan.file_page = 0
        try:
            code, items = self.pan.get_dir_by_id(
                folder_id, save=False, all=True, limit=100
            )
        finally:
            self.pan.file_page, self.pan.total, self.pan.all_file = cached_state
        if code != 0:
            return
        for child in items:
            name = child.get("FileName", "")
            child_path = rel_path + "/" + name if rel_path else name
            if int(child.get("Type", 0)) == 1:
                self._collect_folder(int(child["FileId"]), child_path, result)
            else:
                etag = str(child.get("Etag", "") or "").lower()
                if OfflineService._is_valid_etag(etag):
                    result.append({
                        "path": child_path,
                        "etag": etag,
                        "size": int(child.get("Size", 0) or 0),
                    })
