"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QDialog, QHBoxLayout, QTreeWidgetItem, QVBoxLayout

from qfluentwidgets import (
    TreeWidget,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    FluentIcon as FIF,
)

from ..common.i18n import tr
from ..common.log import get_logger
from ..tasks.file_tasks import LoadFolderListTask, connect_tracked
from ..tasks.signals import _FolderListSignals

logger = get_logger(__name__)

# 图标缓存（懒加载）
_ICON_FOLDER = None


def _folder_icon():
    global _ICON_FOLDER
    if _ICON_FOLDER is None:
        _ICON_FOLDER = FIF.FOLDER.icon()
    return _ICON_FOLDER


class FolderSelectDialog(QDialog):
    """选择目标文件夹对话框（懒加载目录树）。

    通过 Pan123 门面加载目录列表，遵循 View 层不直接访问 NetSession 的约束。
    """

    def __init__(self, pan, exclude_dir_ids=(), parent=None, multi_select=False, title=None):
        super().__init__(parent)
        self._pan = pan
        self._exclude_dir_ids = set(int(x) for x in exclude_dir_ids)
        self._multi_select = multi_select
        self._selected_dir_id = None
        self._selected_dir_name = ""
        # 多选模式：已勾选目录 ID（dict 充当有序集合，保持勾选顺序）
        self._checked_dir_ids = {}
        # 持有后台任务引用，防止任务/信号被 GC 回收
        self._pending_tasks = []

        dialog_title = title or tr("file.move_title", "选择目标文件夹")
        self.setWindowTitle(dialog_title)
        self.resize(380, 460)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title_label = TitleLabel(dialog_title)
        layout.addWidget(title_label)

        self._tree = TreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumHeight(300)
        self._tree.itemExpanded.connect(self.__onItemExpanded)
        self._tree.itemClicked.connect(self.__onItemClicked)
        self._tree.itemChanged.connect(self.__onItemChanged)
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
        root.setIcon(0, _folder_icon())
        root.setData(0, Qt.ItemDataRole.UserRole, 0)
        root.setData(0, Qt.ItemDataRole.UserRole + 1, False)
        if self._multi_select:
            self.__set_checkable(root)
        self._tree.addTopLevelItem(root)
        self.__add_placeholder(root)
        self._tree.expandItem(root)

    @staticmethod
    def __add_placeholder(parent_item):
        placeholder = QTreeWidgetItem([""])
        placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
        parent_item.addChild(placeholder)

    @staticmethod
    def __set_checkable(item):
        """多选模式：让条目带复选框（初始未勾选）。"""
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)

    def __onItemExpanded(self, item):
        self.__ensure_loaded(item)

    def __onItemClicked(self, item):
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if dir_id is None:
            return
        if self._multi_select:
            # 多选模式：勾选状态由复选框管理，点击条目仅触发懒加载
            self.__ensure_loaded(item)
            return
        self.__ensure_loaded(item)
        self._selected_dir_id = int(dir_id)
        self._selected_dir_name = item.text(0)
        self.btn_ok.setEnabled(True)

    def __onItemChanged(self, item, column):
        """多选模式：复选框状态变化时收集/移除勾选目录。"""
        if column != 0 or not self._multi_select:
            return
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if dir_id is None:
            return
        fid = int(dir_id)
        if item.checkState(0) == Qt.CheckState.Checked:
            self._checked_dir_ids.setdefault(fid, None)
        else:
            self._checked_dir_ids.pop(fid, None)
        # 按钮可能尚未创建（__build_root 设置根节点复选框期间触发的 itemChanged）
        if hasattr(self, "btn_ok"):
            self.btn_ok.setEnabled(bool(self._checked_dir_ids))

    def __ensure_loaded(self, item):
        loaded = item.data(0, Qt.ItemDataRole.UserRole + 1)
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if loaded or dir_id is None:
            return

        # 标记已加载（防止重复触发），后台加载子文件夹
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        item.takeChildren()

        signals = _FolderListSignals()
        task = LoadFolderListTask(self._pan, int(dir_id), signals)
        connect_tracked(
            self, signals, "finished",
            lambda did, folders, err, it=item: self.__onFolderLoaded(
                it, did, folders, err
            ),
            task,
        )
        QThreadPool.globalInstance().start(task)

    def __onFolderLoaded(self, item, dir_id, folders, error):
        """子文件夹加载完成回调（主线程）。"""
        try:
            if error or not item.treeWidget():
                return
            if item.data(0, Qt.ItemDataRole.UserRole) != dir_id:
                return  # 用户已切换，丢弃过期结果
        except RuntimeError:
            return  # 对话框已销毁

        for folder in folders:
            fid = int(folder.get("FileId", 0))
            if fid in self._exclude_dir_ids:
                continue
            child = QTreeWidgetItem([folder.get("FileName", "")])
            child.setIcon(0, _folder_icon())
            child.setData(0, Qt.ItemDataRole.UserRole, fid)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, False)
            if self._multi_select:
                self.__set_checkable(child)
                # 懒加载重载后恢复已勾选状态
                if fid in self._checked_dir_ids:
                    child.setCheckState(0, Qt.CheckState.Checked)
            item.addChild(child)
            self.__add_placeholder(child)

    def __on_ok(self):
        if self._multi_select:
            if not self._checked_dir_ids:
                return
        elif self._selected_dir_id is None:
            return
        self.accept()

    def selected_dir_id(self):
        """返回所选目标目录 ID（0 表示根目录）。

        多选模式下始终返回 None，请使用 selected_dir_ids()。
        """
        return self._selected_dir_id

    def selected_dir_ids(self):
        """返回多选模式下所选目标目录 ID 列表（0 表示根目录，按勾选顺序）。

        单选模式下返回空列表，请使用 selected_dir_id()。
        """
        return list(self._checked_dir_ids)

    def selected_dir_name(self):
        """返回所选目录名称（根目录为「根目录」）。"""
        if self._selected_dir_id == 0:
            return tr("file.root_dir", "根目录")
        return self._selected_dir_name or f"#{self._selected_dir_id}"
