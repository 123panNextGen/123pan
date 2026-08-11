"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMenu,
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar

from ..common.i18n import tr
from ..common.log import get_logger
from ..tasks.file_tasks import (
    BatchDeleteTask,
    CreateFolderTask,
    CreateShareTask,
    DeleteFileTask,
    GetDownloadLinkTask,
    CopyFileTask,
    MoveFileTask,
    RenameFileTask,
    UploadFolderTask,
    connect_tracked,
)
from ..tasks.signals import (
    _DownloadLinkSignals,
    _OpFinishedSignals,
    _ShareCreateSignals,
    _UploadFolderSignals,
)
from .dialogs import InputDialog
from .folder_select_dialog import FolderSelectDialog
from .icons import icon as _icon

logger = get_logger(__name__)


class FileActionsMixin:
    """文件操作逻辑（新建/上传/下载/删除/重命名/移动/复制/分享/预览等）。"""

    def _createNewFolder(self):
        """创建新文件夹"""

        # 使用新建文件夹弹窗
        dialog = InputDialog(tr("file.new_folder", "新建文件夹"), tr("file.new_folder_hint", "请输入文件夹名称"), tr("file.new_folder_default", "新建文件夹"), self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            folder_name = dialog.get_input_text()

            # 检查文件夹名称是否为空
            if not folder_name.strip():
                InfoBar.warning(
                    title=tr("file.msg_input_error", "输入错误"), content=tr("file.msg_enter_folder_name", "请输入文件夹名称"), parent=self
                )
                return

            # 在主线程创建信号
            signals = _OpFinishedSignals()
            task = CreateFolderTask(
                self.pan, folder_name, self.current_dir_id, signals, self
            )
            connect_tracked(self, signals, "finished", self._onCreateFolderFinished, task)

            # 提交任务到线程池
            QThreadPool.globalInstance().start(task)

    def _onCreateFolderFinished(
        self, result, folder_name, new_name, error, file_items, folder_items
    ):
        """创建文件夹完成后的回调 - 只负责UI更新"""
        if result:
            InfoBar.success(
                title=tr("file.msg_create_success", "创建成功"),
                content=tr("file.msg_folder_created", "文件夹 '{}' 创建成功").format(folder_name),
                parent=self,
            )

            # 更新文件列表（轻量级UI操作）
            self._updateFileListUI(file_items)

            # 更新树结构（轻量级UI操作）
            self._updateTreeUI(folder_items)

            # 重新选择当前目录
            current_item = self._findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            if error:
                InfoBar.error(
                    title=tr("file.msg_create_failed", "创建失败"),
                    content=tr("file.msg_create_folder_error", "创建文件夹时发生错误: {}").format(error),
                    parent=self,
                )
            else:
                InfoBar.error(title=tr("file.msg_create_failed", "创建失败"), content=tr("file.msg_create_folder_failed", "创建文件夹失败"), parent=self)

    def _uploadFile(self):
        """上传文件"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, tr("file.upload_title", "选择要上传的文件"))

        if file_paths:
            self._addUploadTasks(file_paths)

    def _showUploadMenu(self):
        """上传按钮下拉菜单：上传文件 / 上传文件夹。"""
        menu = QMenu(self)
        file_action = QAction(
            _icon(FIF.DOCUMENT), tr("file.upload_files", "上传文件"), self
        )
        file_action.triggered.connect(self._uploadFile)
        folder_action = QAction(
            _icon(FIF.FOLDER), tr("file.upload_folder", "上传文件夹"), self
        )
        folder_action.triggered.connect(self._uploadFolder)
        menu.addAction(file_action)
        menu.addAction(folder_action)
        pos = self.uploadButton.mapToGlobal(self.uploadButton.rect().bottomLeft())
        menu.exec(pos)

    def _uploadFolder(self):
        """选择文件夹并递归上传（保留目录结构）。"""
        folder = QFileDialog.getExistingDirectory(
            self, tr("file.upload_folder_title", "选择要上传的文件夹")
        )
        if folder:
            self._addFolderUpload(folder)

    def _addFolderUpload(self, local_folder):
        """启动文件夹上传任务（后台扫描 + 建目录，完成后加入上传队列）。"""
        signals = _UploadFolderSignals()
        task = UploadFolderTask(self.pan, local_folder, self.current_dir_id, signals)
        connect_tracked(self, signals, "finished", self._onUploadFolderFinished, task)
        QThreadPool.globalInstance().start(task)

    def _onUploadFolderFinished(self, files, error):
        """文件夹上传扫描完成回调：将文件加入上传队列。"""
        if error or not files:
            InfoBar.error(
                title=tr("file.msg_folder_upload_failed", "文件夹上传失败"),
                content=error or tr("file.msg_folder_empty", "文件夹中没有可上传的文件"),
                parent=self,
            )
            return

        for local_path, dir_id in files:
            path = Path(local_path)
            file_size = path.stat().st_size
            if self.transfer_interface:
                self.transfer_interface.add_upload_task(
                    path.name, file_size, local_path, dir_id
                )
        InfoBar.success(
            title=tr("file.msg_upload_success", "上传文件"),
            content=tr("file.msg_upload_added", "已添加 {} 个上传任务").format(len(files)),
            parent=self,
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入时接受文件/文件夹拖放"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """拖拽移动时接受"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """处理拖放文件/文件夹（文件夹递归上传）。"""
        urls = event.mimeData().urls()
        if not urls:
            return
        file_paths = []
        folder_paths = []
        for url in urls:
            path = url.toLocalFile()
            if not path:
                continue
            p = Path(path)
            if p.is_file():
                file_paths.append(path)
            elif p.is_dir():
                folder_paths.append(path)

        if file_paths:
            self._addUploadTasks(file_paths)
        for folder in folder_paths:
            self._addFolderUpload(folder)
        if not file_paths and not folder_paths:
            InfoBar.warning(
                title=tr("file.drop_warn_title", "拖拽上传"),
                content=tr("file.drop_warn_content", "只支持拖放文件或文件夹"),
                parent=self,
            )

    def _addUploadTasks(self, file_paths):
        """添加上传任务（共用方法）"""
        logger.info("准备上传 %d 个文件", len(file_paths))
        for file_path in file_paths:
            path = Path(file_path)
            file_name = path.name
            file_size = path.stat().st_size
            logger.debug(
                "上传文件: name=%s, size=%s, dir=%s",
                file_name,
                file_size,
                self.current_dir_id,
            )
            if self.transfer_interface:
                self.transfer_interface.add_upload_task(
                    file_name, file_size, file_path, self.current_dir_id
                )

        InfoBar.success(
            title=tr("file.msg_upload_success", "上传文件"),
            content=tr("file.msg_upload_added", "已添加 {} 个上传任务").format(len(file_paths)),
            parent=self,
        )

    def _downloadFile(self):
        """下载文件（支持批量）"""
        selected_rows = self._getSelectedRows()
        if not selected_rows:
            InfoBar.warning(title=tr("file.msg_download_error", "下载错误"), content=tr("file.msg_select_file_download", "请选择要下载的文件"), parent=self)
            return

        from app.common.config import ConfigManager

        ask_download_location = ConfigManager.get_setting("askDownloadLocation", True)
        default_download_path = ConfigManager.get_setting(
            "defaultDownloadPath", str(Path.home() / "Downloads")
        )

        # 批量下载时：如果"每次询问"，先选目录；如果不询问，统一使用默认目录
        if ask_download_location and len(selected_rows) > 1:
            save_dir = QFileDialog.getExistingDirectory(
                self, tr("file.download_dir_title", "选择下载保存目录"), default_download_path
            )
            if not save_dir:
                return
            ask_download_location = False  # 批量模式下不再逐个询问
        else:
            save_dir = default_download_path

        count = 0
        for row in selected_rows:
            name_item = self.fileTable.item(row, 0)
            file_id = name_item.data(Qt.ItemDataRole.UserRole)
            file_name = name_item.text()
            file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

            if file_type == 1:
                file_name = file_name + ".zip"

            if ask_download_location:
                save_path, _ = QFileDialog.getSaveFileName(
                    self, tr("file.save_file_title", "保存文件"), str(Path(default_download_path) / file_name)
                )
                if not save_path:
                    continue
            else:
                save_path = str(Path(save_dir) / file_name)

            file_info = self._findFileById(file_id)
            file_size = int(file_info.get("Size", 0) or 0) if file_info else 0

            if self.transfer_interface:
                self.transfer_interface.add_download_task(
                    file_name, file_size, file_id, save_path, self.current_dir_id
                )
            count += 1

        if count > 0:
            InfoBar.success(
                title=tr("file.msg_download_success", "下载文件"),
                content=tr("file.msg_download_added", "已添加 {} 个下载任务").format(count),
                parent=self,
            )

    def _refreshFileList(self, force=False):
        """刷新文件列表。

        Args:
            force: 是否强制从服务器获取（跳过缓存）
        """
        self.searchBox.clear()
        self._table_mgr.search_text = ""
        self._loadCurrentList(force_refresh=force)
        self.load_and_update_storage_info()

    def _getSelectedRows(self):
        """获取所有选中行的行号列表（去重）。"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            return []
        rows = sorted(set(item.row() for item in selected_items))
        return rows

    def _deleteFile(self, file_id=None, file_name=None):
        """删除文件（支持批量）"""

        # 如果没有提供file_id和file_name，则从选中的文件批量获取
        if file_id is None or file_name is None:
            selected_rows = self._getSelectedRows()
            if not selected_rows:
                InfoBar.warning(
                    title=tr("file.msg_delete_error", "删除错误"), content=tr("file.msg_select_file_delete", "请选择要删除的文件"), parent=self
                )
                return

            if len(selected_rows) == 1:
                # 单文件删除走原有路径
                row = selected_rows[0]
                name_item = self.fileTable.item(row, 0)
                file_id = name_item.data(Qt.ItemDataRole.UserRole)
                file_name = name_item.text()
            else:
                # 批量删除
                self._batchDeleteFiles(selected_rows)
                return

        # 单文件删除
        signals = _OpFinishedSignals()
        task = DeleteFileTask(
            self.pan, file_id, file_name, self.current_dir_id, signals, self
        )
        connect_tracked(self, signals, "finished", self._onDeleteFileFinished, task)
        QThreadPool.globalInstance().start(task)

    def _batchDeleteFiles(self, selected_rows):
        """批量删除文件。"""
        file_infos = []
        for row in selected_rows:
            name_item = self.fileTable.item(row, 0)
            fid = name_item.data(Qt.ItemDataRole.UserRole)
            fname = name_item.text()
            file_infos.append((fid, fname))

        # 在主线程创建信号
        signals = _OpFinishedSignals()
        task = BatchDeleteTask(
            self.pan, file_infos, self.current_dir_id, signals, self
        )
        connect_tracked(
            self, signals, "finished",
            lambda success, name, new_name, error, items, folders: self._onBatchDeleteFinished(
                success, name, new_name, error, items, folders
            ),
            task,
        )
        QThreadPool.globalInstance().start(task)

    def _onBatchDeleteFinished(
        self, success, file_name, new_name, error, file_items, folder_items
    ):
        """批量删除完成后的回调"""
        if success:
            InfoBar.success(
                title=tr("file.msg_batch_delete_success", "批量删除成功"),
                content=file_name,
                parent=self,
            )
            self._updateFileListUI(file_items)
            self._updateTreeUI(folder_items)
            current_item = self._findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            InfoBar.error(
                title=tr("file.msg_batch_delete_failed", "批量删除失败"),
                content=error or "批量删除失败",
                parent=self,
            )

    def _onDeleteFileFinished(
        self, success, file_name, new_name, error, file_items, folder_items
    ):
        """删除文件完成后的回调 - 只负责UI更新"""

        if success:
            # 显示成功信息
            InfoBar.success(
                title=tr("file.msg_delete_success", "删除成功"),
                content=tr("file.msg_file_deleted", "文件 '{}' 已成功删除").format(file_name),
                parent=self,
            )

            # 更新文件列表（轻量级UI操作）
            self._updateFileListUI(file_items)

            # 更新树结构（轻量级UI操作）
            self._updateTreeUI(folder_items)

            # 重新选择当前目录
            current_item = self._findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            if error:
                # 显示错误信息
                InfoBar.error(
                    title=tr("file.msg_delete_failed", "删除失败"),
                    content=tr("file.msg_delete_file_error", "删除文件时发生错误: {}").format(error),
                    parent=self,
                )
            else:
                # 显示错误信息
                InfoBar.error(title=tr("file.msg_delete_failed", "删除失败"), content=tr("file.msg_file_not_found", "文件不存在"), parent=self)

    def _renameFile(self):
        """重命名文件"""

        # 获取选中的文件
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_rename_error", "重命名错误"), content=tr("file.msg_select_file_rename", "请选择要重命名的文件"), parent=self
            )
            return

        # 获取选中行的文件信息
        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        old_name = name_item.text()
        file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

        # 使用重命名对话框获取新名称
        dialog = InputDialog(tr("file.menu_rename", "重命名"), "请输入新的名称", old_name, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        new_name = dialog.get_input_text()

        # 检查新名称是否为空
        if not new_name:
            InfoBar.warning(title=tr("file.msg_rename_error", "重命名错误"), content=tr("file.msg_name_empty", "名称不能为空"), parent=self)
            return

        # 检查新名称是否与旧名称相同
        if new_name == old_name:
            InfoBar.warning(
                title=tr("file.msg_rename_error", "重命名错误"),
                content=tr("file.msg_name_same", "新名称与旧名称相同"),
                parent=self,
            )
            return

        # 检查新名称是否包含无效字符
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in new_name for char in invalid_chars):
            InfoBar.warning(
                title=tr("file.msg_rename_error", "重命名错误"),
                content=tr("file.msg_invalid_chars", "名称不能包含以下字符: {}").format(" ".join(invalid_chars)),
                parent=self,
            )
            return

        # 在主线程创建信号
        signals = _OpFinishedSignals()
        task = RenameFileTask(
            self.pan, file_id, old_name, new_name, self.current_dir_id, signals, self
        )
        connect_tracked(self, signals, "finished", self._onRenameFileFinished, task)

        # 提交任务到线程池
        QThreadPool.globalInstance().start(task)

    def _onRenameFileFinished(
        self, success, old_name, new_name, error, file_items, folder_items
    ):
        """重命名文件完成后的回调 - 只负责UI更新"""

        if success:
            # 显示成功信息
            InfoBar.success(
                title=tr("file.msg_rename_success", "重命名成功"),
                content=tr("file.msg_file_renamed", "文件 '{}' 已成功重命名为 '{}'").format(old_name, new_name),
                parent=self,
            )

            # 更新文件列表（轻量级UI操作）
            self._updateFileListUI(file_items)

            # 更新树结构（轻量级UI操作）
            self._updateTreeUI(folder_items)

            # 重新选择当前目录
            current_item = self._findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            if error:
                # 显示错误信息
                InfoBar.error(
                    title=tr("file.msg_rename_failed", "重命名失败"),
                    content=tr("file.msg_rename_file_error", "重命名文件时发生错误: {}").format(error),
                    parent=self,
                )
            else:
                # 显示错误信息
                InfoBar.error(title=tr("file.msg_rename_failed", "重命名失败"), content=tr("file.msg_rename_failed", "重命名失败"), parent=self)

    def _copyFile(self):
        """复制选中文件/文件夹到目标目录"""

        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_copy_error", "复制错误"),
                content=tr("file.msg_select_file_move", "请选择要复制的文件或文件夹"),
                parent=self,
            )
            return

        file_infos = []
        seen = set()
        for item in selected_items:
            if item.column() != 0:
                continue
            row = item.row()
            name_item = self.fileTable.item(row, 0)
            if name_item is None:
                continue
            file_id = int(name_item.data(Qt.ItemDataRole.UserRole) or 0)
            if file_id in seen:
                continue
            seen.add(file_id)
            file_infos.append((file_id, name_item.text()))

        if not file_infos:
            return

        # 不能复制到当前目录自身；支持一次选择多个目标目录
        dialog = FolderSelectDialog(
            self.pan,
            exclude_dir_ids=(self.current_dir_id,),
            parent=self,
            multi_select=True,
            title=tr("file.copy_title", "选择目标文件夹（可多选）"),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        targets = dialog.selected_dir_ids()
        if not targets:
            return
        # 对话框已排除当前目录，这里再兜底过滤一遍
        targets = [t for t in targets if t != self.current_dir_id]
        if not targets:
            return

        signals = _OpFinishedSignals()
        task = CopyFileTask(
            self.pan, file_infos, targets, self.current_dir_id, signals, self
        )
        connect_tracked(self, signals, "finished", self._onCopyFileFinished, task)
        QThreadPool.globalInstance().start(task)

    def _onCopyFileFinished(
        self, success, name, new_name, error, file_items, folder_items
    ):
        """复制文件完成后的回调 - 只负责UI更新"""
        if success:
            if error:
                # 部分目标复制失败（其余成功）：警告提示
                InfoBar.warning(
                    title=tr("file.msg_copy_partial", "部分复制失败"),
                    content=tr("file.msg_copy_partial_detail", "以下目标目录复制失败: {}").format(error),
                    parent=self,
                )
            else:
                InfoBar.success(
                    title=tr("file.msg_copy_success", "复制成功"),
                    content=tr("file.msg_copy_done", "文件已复制到目标目录"),
                    parent=self,
                )
            # 更新文件列表与目录树（轻量级UI操作）
            self._updateFileListUI(file_items)
            self._updateTreeUI(folder_items)
            current_item = self._findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            msg = error or tr("file.msg_copy_failed", "复制失败")
            InfoBar.error(
                title=tr("file.msg_copy_failed", "复制失败"),
                content=tr("file.msg_copy_file_error", "复制文件时发生错误: {}").format(msg),
                parent=self,
            )

    def _moveFile(self):
        """移动选中文件/文件夹到目标目录"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_move_error", "移动错误"),
                content=tr("file.msg_select_file_move", "请选择要移动的文件或文件夹"),
                parent=self,
            )
            return

        file_infos = []
        seen = set()
        for item in selected_items:
            if item.column() != 0:
                continue
            row = item.row()
            name_item = self.fileTable.item(row, 0)
            if name_item is None:
                continue
            file_id = int(name_item.data(Qt.ItemDataRole.UserRole) or 0)
            if file_id in seen:
                continue
            seen.add(file_id)
            file_infos.append((file_id, name_item.text()))

        if not file_infos:
            return

        # 不能移动到当前目录自身
        dialog = FolderSelectDialog(
            self.pan, exclude_dir_ids=(self.current_dir_id,), parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target = dialog.selected_dir_id()
        if target is None or target == self.current_dir_id:
            return

        signals = _OpFinishedSignals()
        task = MoveFileTask(
            self.pan, file_infos, target, self.current_dir_id, signals, self
        )
        connect_tracked(self, signals, "finished", self._onMoveFileFinished, task)
        QThreadPool.globalInstance().start(task)

    def _onMoveFileFinished(
        self, success, name, new_name, error, file_items, folder_items
    ):
        """移动文件完成后的回调 - 只负责UI更新"""
        if success:
            InfoBar.success(
                title=tr("file.msg_move_success", "移动成功"),
                content=tr("file.msg_move_done", "文件已移动到目标目录"),
                parent=self,
            )
            # 更新文件列表与目录树（轻量级UI操作）
            self._updateFileListUI(file_items)
            self._updateTreeUI(folder_items)
            current_item = self._findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            msg = error or tr("file.msg_move_failed", "移动失败")
            InfoBar.error(
                title=tr("file.msg_move_failed", "移动失败"),
                content=tr("file.msg_move_file_error", "移动文件时发生错误: {}").format(msg),
                parent=self,
            )

    # noinspection PyTypeChecker
    def _onFileTableContextMenu(self, position):
        """文件表格右键菜单"""
        # 获取鼠标点击位置的行
        index = self.fileTable.indexAt(position)
        if not index.isValid():
            return

        # 右键点击的行未选中时选中它（保留已有多选）
        if not self.fileTable.selectionModel().isRowSelected(
            index.row(), index.parent()
        ):
            self.fileTable.selectRow(index.row())

        # 创建右键菜单
        menu = QMenu(self)

        # 添加获取下载链接菜单项
        copy_link_action = QAction(_icon(FIF.LINK), tr("file.menu_copy_link", "获取下载链接"), self)
        copy_link_action.triggered.connect(self._copyDownloadLink)
        menu.addAction(copy_link_action)

        # 添加预览菜单项
        preview_action = QAction(_icon(FIF.VIEW), tr("file.menu_preview", "预览"), self)
        preview_action.triggered.connect(self._previewFile)
        menu.addAction(preview_action)

        # 添加分享菜单项
        share_action = QAction(_icon(FIF.LINK), tr("file.menu_share", "分享"), self)
        share_action.triggered.connect(self._shareFile)
        menu.addAction(share_action)

        # 添加重命名菜单项
        rename_action = QAction(_icon(FIF.EDIT), tr("file.menu_rename", "重命名"), self)
        rename_action.triggered.connect(self._renameFile)
        menu.addAction(rename_action)

        # 添加复制菜单项
        copy_action = QAction(_icon(FIF.COPY), tr("file.menu_copy", "复制到"), self)
        copy_action.triggered.connect(self._copyFile)
        menu.addAction(copy_action)

        # 添加移动菜单项
        move_action = QAction(_icon(FIF.RIGHT_ARROW), tr("file.menu_move", "移动到"), self)
        move_action.triggered.connect(self._moveFile)
        menu.addAction(move_action)

        # 添加删除菜单项
        delete_action = QAction(_icon(FIF.DELETE), tr("file.delete", "删除"), self)
        delete_action.triggered.connect(self._deleteFile)
        menu.addAction(delete_action)

        # 显示菜单
        menu.exec(self.fileTable.mapToGlobal(position))

    def _copyDownloadLink(self):
        """复制文件下载链接到剪贴板"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(title=tr("file.msg_copy_link_failed", "复制链接失败"), content=tr("file.msg_select_one_file", "请选择一个文件"), parent=self)
            return

        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        logger.info("获取下载链接: name=%s, id=%s", file_name, file_id)

        file_detail = self._findFileById(file_id)

        if not file_detail:
            logger.warning("未找到文件详情: id=%s", file_id)
            InfoBar.error(title=tr("file.msg_copy_link_failed", "复制链接失败"), content=tr("file.msg_file_detail_not_found", "无法找到文件详情"), parent=self)
            return

        # 后台获取下载链接，避免主线程网络请求阻塞
        self._last_copy_name = file_name
        signals = _DownloadLinkSignals()
        task = GetDownloadLinkTask(self.pan, file_detail, signals)
        connect_tracked(self, signals, "finished", self._onDownloadLinkReady, task)
        QThreadPool.globalInstance().start(task)

    def _onDownloadLinkReady(self, url, error):
        """下载链接获取完成回调（主线程）。"""
        if error or not url:
            logger.error("获取下载链接失败: %s", error)
            InfoBar.error(
                title=tr("file.msg_copy_link_failed", "复制链接失败"),
                content=tr("file.msg_get_link_failed", "获取下载链接失败"),
                parent=self,
            )
            return

        clipboard = QApplication.clipboard()
        clipboard.setText(url)
        logger.info("下载链接已复制: %s", url[:80])
        InfoBar.success(
            title=tr("file.msg_copy_success", "复制成功"),
            content=tr("file.msg_link_copied", "已复制 {} 的下载链接到剪贴板").format(self._last_copy_name or ""),
            parent=self,
        )

    def _shareFile(self):
        """为选中文件/文件夹生成分享链接并复制到剪贴板（可选设置密码）。"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_share_failed", "分享失败"), content=tr("file.msg_select_file_share", "请选择一个文件或文件夹"), parent=self
            )
            return

        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        logger.info("生成分享链接: name=%s, id=%s", file_name, file_id)

        pwd, ok = QInputDialog.getText(
            self, tr("file.share_pwd_title", "设置分享密码(可选)"), tr("file.share_pwd_label", "分享密码 (留空则无密码):")
        )
        if not ok:
            logger.debug("用户取消分享密码设置")
            return

        # 后台创建分享链接，避免主线程网络请求阻塞
        self._last_share_name = file_name
        signals = _ShareCreateSignals()
        task = CreateShareTask(self.pan, int(file_id), pwd or "", signals)
        connect_tracked(self, signals, "finished", self._onShareCreated, task)
        QThreadPool.globalInstance().start(task)

    def _onShareCreated(self, share_url, error):
        """分享链接创建完成回调（主线程）。"""
        if error or not share_url:
            logger.error("生成分享链接失败: %s", error)
            InfoBar.error(
                title=tr("file.msg_share_failed", "分享失败"),
                content=tr("file.msg_share_gen_failed", "生成分享链接失败"),
                parent=self,
            )
            return

        QApplication.clipboard().setText(share_url)
        logger.info("分享成功: %s -> %s", self._last_share_name or "", share_url)
        InfoBar.success(
            title=tr("file.msg_share_success", "分享成功"),
            content=tr("file.msg_share_generated", "已生成分享链接并复制到剪贴板：{}").format(share_url),
            parent=self,
        )

    def _findFileById(self, file_id):
        """从缓存的文件列表中根据 file_id 查找文件详情。

        优先使用 O(1) 索引（当前目录），
        回退到 pan.list（历史缓存）。
        """
        item = self._table_mgr.find_by_id(file_id)
        if item is not None:
            return item
        # 回退到 pan.list
        for item in self.pan.list:
            if str(item.get("FileId")) == str(file_id):
                return item
        return None

    def _previewFile(self):
        """预览选中的文件。

        支持图片、视频、音频、文本等格式。
        不支持预览的格式将弹出提示。
        """
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_preview_failed", "预览失败"), content=tr("file.msg_select_one_file", "请选择一个文件"), parent=self
            )
            return

        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        if name_item is None:
            return

        file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)
        if file_type == 1:
            InfoBar.warning(
                title="预览失败",
                content=tr("file.msg_folder_no_preview", "文件夹不支持预览，请双击打开"),
                parent=self,
            )
            return

        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        logger.info("预览文件: name=%s, id=%s", file_name, file_id)

        # 查找文件详情（从缓存的文件列表中查找，而非 pan.list）
        file_detail = self._findFileById(file_id)

        if not file_detail:
            InfoBar.error(
                title="预览失败",
                content="无法找到文件详情",
                parent=self,
            )
            return

        # 检查是否支持预览
        from ..preview import is_preview_supported

        if not is_preview_supported(file_name):
            InfoBar.warning(
                title=tr("file.msg_preview_unsupported", "不支持预览"),
                content=tr("file.msg_preview_unsupported_type", "不支持预览此文件类型: {}").format(file_name),
                parent=self,
            )
            return

        # 打开预览对话框
        from ..preview.preview_dialog import PreviewDialog

        dialog = PreviewDialog(self.pan, file_detail, self)
        dialog.exec()
