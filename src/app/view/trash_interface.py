"""回收站管理界面。

显示回收站中的文件列表，支持恢复和永久删除操作。
"""

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QVBoxLayout,
    QWidget,
    QTableWidgetItem,
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    TableWidget,
    PushButton,
    InfoBar,
)

from ..common.style_sheet import StyleSheet
from ..common.utils import format_file_size
from ..common.api import Pan123
from ..common.log import get_logger
from ..tasks.signals import _OpFinishedSignals

logger = get_logger(__name__)


class TrashInterface(QWidget):
    """回收站页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("TrashInterface")

        self.pan = None
        self._trash_items = []

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        self.__createTopBar()
        self.__createContent()
        self.__initWidget()

    def set_pan(self, pan):
        """设置 Pan123 实例"""
        self.pan = pan

    def __createTopBar(self):
        self.topBarFrame = QFrame(self)
        self.topBarFrame.setObjectName("frame")
        self.topBarLayout = QHBoxLayout(self.topBarFrame)
        self.topBarLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarLayout.setSpacing(8)

        self.refreshButton = PushButton(
            FIF.UPDATE.icon(), "刷新", self.topBarFrame
        )
        self.restoreButton = PushButton(
            FIF.LEFT_ARROW.icon(), "恢复", self.topBarFrame
        )
        self.deleteButton = PushButton(
            FIF.DELETE.icon(), "永久删除", self.topBarFrame
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
        self.trashTable.setHorizontalHeaderLabels(["名称", "类型", "大小"])
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

        self.mainLayout.addWidget(self.listFrame, 1)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()

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
        """刷新回收站列表"""
        if not self.pan:
            logger.warning("回收站刷新: pan 未设置")
            return

        try:
            items = self.pan._file.recycle()
            self._trash_items = items
            self.__updateTrashTableUI()
            logger.info("回收站列表已刷新: %d 个文件", len(items))
        except Exception as e:
            logger.error("回收站刷新失败: %s", e)
            InfoBar.error(
                title="刷新失败",
                content=f"获取回收站列表失败: {e}",
                parent=self,
            )

    def __updateTrashTableUI(self):
        """更新回收站表格"""
        self.trashTable.setRowCount(len(self._trash_items))
        for row, item in enumerate(self._trash_items):
            file_name = item.get("FileName", "")
            file_type = int(item.get("Type", 0))
            file_size = int(item.get("Size", 0) or 0)

            type_text = "文件夹" if file_type == 1 else "文件"
            size_text = format_file_size(file_size)

            name_item = QTableWidgetItem(file_name)
            name_item.setIcon(
                FIF.FOLDER.icon() if file_type == 1 else FIF.DOCUMENT.icon()
            )
            type_item = QTableWidgetItem(type_text)
            size_item = QTableWidgetItem(size_text)

            self.trashTable.setItem(row, 0, name_item)
            self.trashTable.setItem(row, 1, type_item)
            self.trashTable.setItem(row, 2, size_item)

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
        """恢复选中的文件"""
        selected = self.__getSelectedItems()
        if not selected:
            InfoBar.warning(
                title="恢复文件",
                content="请选择要恢复的文件",
                parent=self,
            )
            return

        try:
            for file_info in selected:
                self.pan._file.delete_file(
                    self._trash_items, file_info, by_num=False, operation=False
                )

            file_names = ", ".join(
                item.get("FileName", "") for item in selected[:3]
            )
            suffix = "..." if len(selected) > 3 else ""
            InfoBar.success(
                title="恢复成功",
                content=f"已恢复 {len(selected)} 个文件: {file_names}{suffix}",
                parent=self,
            )
            self.__refreshTrashList()
        except Exception as e:
            logger.error("恢复文件失败: %s", e)
            InfoBar.error(
                title="恢复失败",
                content=f"恢复文件时发生错误: {e}",
                parent=self,
            )

    def __permanentlyDeleteSelected(self):
        """永久删除选中的文件（从回收站彻底删除 = 再次删除）"""
        selected = self.__getSelectedItems()
        if not selected:
            InfoBar.warning(
                title="永久删除",
                content="请选择要永久删除的文件",
                parent=self,
            )
            return

        try:
            for file_info in selected:
                self.pan._file.delete_file(
                    self._trash_items, file_info, by_num=False, operation=True
                )

            file_names = ", ".join(
                item.get("FileName", "") for item in selected[:3]
            )
            suffix = "..." if len(selected) > 3 else ""
            InfoBar.success(
                title="删除成功",
                content=f"已永久删除 {len(selected)} 个文件: {file_names}{suffix}",
                parent=self,
            )
            self.__refreshTrashList()
        except Exception as e:
            logger.error("永久删除失败: %s", e)
            InfoBar.error(
                title="删除失败",
                content=f"永久删除文件时发生错误: {e}",
                parent=self,
            )
