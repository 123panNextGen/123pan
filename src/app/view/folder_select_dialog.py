"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QTreeWidgetItem, QVBoxLayout

from qfluentwidgets import (
    TreeWidget,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    FluentIcon as FIF,
)

from ..common.i18n import tr
from ..common.log import get_logger

logger = get_logger(__name__)


class FolderSelectDialog(QDialog):
    """选择目标文件夹对话框（懒加载目录树）。

    通过 Pan123 门面加载目录列表，遵循 View 层不直接访问 NetSession 的约束。
    """

    def __init__(self, pan, exclude_dir_ids=(), parent=None):
        super().__init__(parent)
        self._pan = pan
        self._exclude_dir_ids = set(int(x) for x in exclude_dir_ids)
        self._selected_dir_id = None

        self.setWindowTitle(tr("file.move_title", "选择目标文件夹"))
        self.resize(380, 460)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = TitleLabel(tr("file.move_title", "选择目标文件夹"))
        layout.addWidget(title)

        self._tree = TreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumHeight(300)
        self._tree.itemExpanded.connect(self.__onItemExpanded)
        self._tree.itemClicked.connect(self.__onItemClicked)
        layout.addWidget(self._tree)

        # 根目录
        self.__build_root()

        h = QHBoxLayout()
        h.addStretch()
        self.btn_cancel = PushButton(tr("dialog.cancel", "取消"))
        self.btn_ok = PrimaryPushButton(tr("dialog.ok", "确定"))
        self.btn_ok.setEnabled(False)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.__on_ok)
        h.addWidget(self.btn_cancel)
        h.addWidget(self.btn_ok)
        layout.addLayout(h)

    def __build_root(self):
        root = QTreeWidgetItem([tr("file.root_dir", "根目录")])
        root.setIcon(0, FIF.FOLDER.icon())
        root.setData(0, Qt.ItemDataRole.UserRole, 0)
        root.setData(0, Qt.ItemDataRole.UserRole + 1, False)
        self._tree.addTopLevelItem(root)
        self.__add_placeholder(root)
        self._tree.expandItem(root)

    @staticmethod
    def __add_placeholder(parent_item):
        placeholder = QTreeWidgetItem([""])
        placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
        parent_item.addChild(placeholder)

    def __onItemExpanded(self, item):
        self.__ensure_loaded(item)

    def __onItemClicked(self, item):
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if dir_id is None:
            return
        self.__ensure_loaded(item)
        self._selected_dir_id = int(dir_id)
        self.btn_ok.setEnabled(True)

    def __ensure_loaded(self, item):
        loaded = item.data(0, Qt.ItemDataRole.UserRole + 1)
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if loaded or dir_id is None:
            return

        item.takeChildren()
        folders = self.__fetch_folders(int(dir_id))
        for folder in folders:
            fid = int(folder.get("FileId", 0))
            if fid in self._exclude_dir_ids:
                continue
            child = QTreeWidgetItem([folder.get("FileName", "")])
            child.setIcon(0, FIF.FOLDER.icon())
            child.setData(0, Qt.ItemDataRole.UserRole, fid)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, False)
            item.addChild(child)
            self.__add_placeholder(child)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)

    def __fetch_folders(self, dir_id):
        """通过 Pan123 门面获取目录下的文件夹列表。"""
        cached_state = (self._pan.file_page, self._pan.total, self._pan.all_file)
        self._pan.file_page = 0
        try:
            code, items = self._pan.get_dir_by_id(
                dir_id, save=False, all=True, limit=100
            )
            if code != 0:
                return []
            return [i for i in items if int(i.get("Type", 0)) == 1]
        except Exception as e:
            logger.error("加载目录失败: dir_id=%s, err=%s", dir_id, e)
            return []
        finally:
            self._pan.file_page, self._pan.total, self._pan.all_file = cached_state

    def __on_ok(self):
        if self._selected_dir_id is None:
            return
        self.accept()

    def selected_dir_id(self):
        """返回所选目标目录 ID（0 表示根目录）。"""
        return self._selected_dir_id
