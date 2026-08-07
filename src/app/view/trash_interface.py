"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QVBoxLayout,
    QWidget,
    QLabel,
    QTableWidgetItem,
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    TableWidget,
    PushButton,
    InfoBar,
)

from PyQt6.QtCore import QThreadPool, Qt

from ..common.style_sheet import StyleSheet
from ..common.utils import format_file_size
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import (
    LoadTrashListTask,
    PermDeleteTrashTask,
    RestoreTrashTask,
    connect_tracked,
)
from ..tasks.signals import _TrashListSignals, _TrashOpSignals

logger = get_logger(__name__)

# 图标缓存：避免每行重复解码 SVG 图标
_ICON_FOLDER = None
_ICON_FILE = None


def _cached_icons():
    global _ICON_FOLDER, _ICON_FILE
    if _ICON_FOLDER is None:
        _ICON_FOLDER = FIF.FOLDER.icon()
        _ICON_FILE = FIF.DOCUMENT.icon()
    return _ICON_FOLDER, _ICON_FILE


class TrashInterface(QWidget):
    """回收站页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("TrashInterface")

        self.pan = None
        self._trash_items = []
        # 持有后台任务引用，防止任务/信号被 GC 回收
        self._pending_tasks = []

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        self.__createTopBar()
        self.__createContent()
        self.__initWidget()

    def set_pan(self, pan):
        """设置 Pan123 实例"""
        self.pan = pan
        # 异步登录期间页面可能已显示：设置 pan 后若可见则立即刷新
        if pan and self.isVisible():
            self.__refreshTrashList()

    def __createTopBar(self):
        self.topBarFrame = QFrame(self)
        self.topBarFrame.setObjectName("frame")
        self.topBarLayout = QHBoxLayout(self.topBarFrame)
        self.topBarLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarLayout.setSpacing(8)

        self.refreshButton = PushButton(
            FIF.UPDATE.icon(), tr("trash.refresh", "刷新"), self.topBarFrame
        )
        self.restoreButton = PushButton(
            FIF.LEFT_ARROW.icon(), tr("trash.restore", "恢复"), self.topBarFrame
        )
        self.deleteButton = PushButton(
            FIF.DELETE.icon(), tr("trash.permanent_delete", "永久删除"), self.topBarFrame
        )

        self.topBarLayout.addWidget(self.refreshButton, 0)
        self.topBarLayout.addWidget(self.restoreButton, 0)
        self.topBarLayout.addWidget(self.deleteButton, 0)
        self.topBarLayout.addStretch(1)

        self.mainLayout.addWidget(self.topBarFrame, 0)

    def __createContent(self):
        self.listFrame = QFrame(self)
        self.listFrame.setObjectName("frame")
        self.listLayout = QVBoxLayout(self.listFrame)
        self.listLayout.setContentsMargins(0, 8, 0, 0)
        self.listLayout.setSpacing(0)

        self.trashTable = TableWidget(self.listFrame)
        self.trashTable.setAlternatingRowColors(True)
        self.trashTable.setColumnCount(3)
        self.trashTable.setHorizontalHeaderLabels([tr("trash.col_name", "名称"), tr("trash.col_type", "类型"), tr("trash.col_size", "大小")])
        self.trashTable.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.trashTable.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.trashTable.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        vertical_header = self.trashTable.verticalHeader()
        if vertical_header is not None:
            vertical_header.hide()
        self.trashTable.setBorderRadius(8)
        self.trashTable.setBorderVisible(True)
        header = self.trashTable.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.listLayout.addWidget(self.trashTable)

        # 空回收站提示（覆盖在表格上）
        self.emptyLabel = QLabel(tr("trash.state_empty", "回收站为空"), self.listFrame)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emptyLabel.setStyleSheet("color: gray; font-size: 14px;")
        self.emptyLabel.hide()

        self.mainLayout.addWidget(self.listFrame, 1)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()

    def resizeEvent(self, event):
        """保持空状态提示与列表区域同步。"""
        super().resizeEvent(event)
        if getattr(self, "emptyLabel", None) is not None and not self.emptyLabel.isHidden():
            self.emptyLabel.setGeometry(self.listFrame.rect())

    def showEvent(self, event):
        """页面显示时自动刷新回收站列表"""
        super().showEvent(event)
        if self.pan:
            self.__refreshTrashList()

    def __connectSignalToSlot(self):
        self.refreshButton.clicked.connect(self.__refreshTrashList)
        self.restoreButton.clicked.connect(self.__restoreSelected)
        self.deleteButton.clicked.connect(self.__permanentlyDeleteSelected)

    def __refreshTrashList(self):
        """刷新回收站列表（后台线程，避免阻塞 GUI）。"""
        if not self.pan:
            logger.warning("回收站刷新: pan 未设置")
            return

        signals = _TrashListSignals()
        task = LoadTrashListTask(self.pan, signals)
        connect_tracked(self, signals, "finished", self.__onTrashListLoaded, task)
        QThreadPool.globalInstance().start(task)

    def __onTrashListLoaded(self, items, error):
        """回收站列表加载完成回调（主线程）。"""
        if error:
            logger.error("回收站刷新失败: %s", error)
            InfoBar.error(
                title=tr("trash.msg_refresh_failed", "刷新失败"),
                content=tr("trash.msg_trash_list_error", "获取回收站列表失败: {}").format(error),
                parent=self,
            )
            return
        self._trash_items = items
        self.__updateTrashTableUI()
        logger.info("回收站列表已刷新: %d 个文件", len(items))

    def __updateTrashTableUI(self):
        """更新回收站表格"""
        count = len(self._trash_items)
        self.trashTable.setRowCount(count)
        self.emptyLabel.setVisible(count == 0)
        if count == 0:
            self.emptyLabel.setGeometry(self.listFrame.rect())
        folder_icon, file_icon = _cached_icons()
        self.trashTable.setUpdatesEnabled(False)
        try:
            for row, item in enumerate(self._trash_items):
                file_name = item.get("FileName", "")
                file_type = int(item.get("Type", 0))
                file_size = int(item.get("Size", 0) or 0)

                type_text = tr("trash.type_folder", "文件夹") if file_type == 1 else tr("trash.type_file", "文件")
                size_text = format_file_size(file_size)

                name_item = QTableWidgetItem(file_name)
                name_item.setIcon(folder_icon if file_type == 1 else file_icon)
                type_item = QTableWidgetItem(type_text)
                size_item = QTableWidgetItem(size_text)

                self.trashTable.setItem(row, 0, name_item)
                self.trashTable.setItem(row, 1, type_item)
                self.trashTable.setItem(row, 2, size_item)
        finally:
            self.trashTable.setUpdatesEnabled(True)

    def __getSelectedItems(self):
        """获取选中的回收站条目信息"""
        selected_rows = set()
        for table_item in self.trashTable.selectedItems():
            selected_rows.add(table_item.row())

        result = []
        for row in sorted(selected_rows):
            if 0 <= row < len(self._trash_items):
                result.append(self._trash_items[row])
        return result

    def __restoreSelected(self):
        """恢复选中的文件（后台任务，避免阻塞 GUI）。"""
        selected = self.__getSelectedItems()
        if not selected:
            InfoBar.warning(
                title=tr("trash.msg_restore_file", "恢复文件"),
                content=tr("trash.msg_select_to_restore", "请选择要恢复的文件"),
                parent=self,
            )
            return

        # 保存当前列表快照与选中信息供后台任务和回调使用
        trash_items = list(self._trash_items)
        self._last_op_count = len(selected)
        self._last_op_names = [item.get("FileName", "") for item in selected]
        signals = _TrashOpSignals()
        task = RestoreTrashTask(self.pan, trash_items, list(selected), signals)
        connect_tracked(self, signals, "finished", self.__onRestoreFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onRestoreFinished(self, success, error):
        """恢复完成回调（主线程）。"""
        if not success:
            logger.error("恢复文件失败: %s", error)
            InfoBar.error(
                title=tr("trash.msg_restore_failed", "恢复失败"),
                content=tr("trash.msg_restore_error", "恢复文件时发生错误: {}").format(error),
                parent=self,
            )
            return

        file_names = ", ".join(getattr(self, "_last_op_names", [])[:3])
        suffix = "..." if getattr(self, "_last_op_count", 0) > 3 else ""
        InfoBar.success(
            title=tr("trash.msg_restore_success", "恢复成功"),
            content=tr("trash.msg_files_restored", "已恢复 {} 个文件: {}").format(getattr(self, "_last_op_count", 0), file_names + suffix),
            parent=self,
        )
        self.__refreshTrashList()

    def __permanentlyDeleteSelected(self):
        """永久删除选中的文件（从回收站彻底删除 = 再次删除）。"""
        selected = self.__getSelectedItems()
        if not selected:
            InfoBar.warning(
                title=tr("trash.permanent_delete", "永久删除"),
                content=tr("trash.msg_select_to_perm_delete", "请选择要永久删除的文件"),
                parent=self,
            )
            return

        file_ids = [int(item.get("FileId", 0)) for item in selected]
        self._last_op_count = len(selected)
        self._last_op_names = [item.get("FileName", "") for item in selected]
        signals = _TrashOpSignals()
        task = PermDeleteTrashTask(self.pan, file_ids, signals)
        connect_tracked(self, signals, "finished", self.__onPermDeleteFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onPermDeleteFinished(self, success, msg):
        """永久删除完成回调（主线程）。"""
        if not success:
            logger.error("永久删除失败: %s", msg)
            InfoBar.error(
                title=tr("trash.msg_perm_delete_failed", "删除失败"),
                content=tr("trash.msg_perm_delete_error", "永久删除文件时发生错误: {}").format(msg),
                parent=self,
            )
            return

        file_names = ", ".join(getattr(self, "_last_op_names", [])[:3])
        suffix = "..." if getattr(self, "_last_op_count", 0) > 3 else ""
        InfoBar.success(
            title=tr("trash.msg_perm_delete_success", "删除成功"),
            content=tr("trash.msg_files_perm_deleted", "已永久删除 {} 个文件: {}").format(getattr(self, "_last_op_count", 0), file_names + suffix),
            parent=self,
        )
        self.__refreshTrashList()
