"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from src.app.view import folder_select_dialog as fsd
from src.app.view.folder_select_dialog import FolderSelectDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePool:
    """阻止目录树懒加载后台任务真实启动的桩。"""

    @classmethod
    def globalInstance(cls):
        return cls()

    def start(self, task):
        pass


@pytest.fixture
def no_background(monkeypatch):
    monkeypatch.setattr(fsd, "QThreadPool", _FakePool)


class TestFolderSelectDialogSingle:
    """单选模式（移动/同步使用）保持原行为。"""

    def test_root_ignores_check(self, qapp, no_background):
        """单选模式不收集勾选状态，确定按钮仍由点击选择驱动。"""
        dialog = FolderSelectDialog(pan=MagicMock())
        root = dialog._tree.topLevelItem(0)
        assert root is not None
        root.setCheckState(0, Qt.CheckState.Checked)
        assert dialog.selected_dir_ids() == []
        assert not dialog.btn_ok.isEnabled()

    def test_click_selects_dir(self, qapp, no_background):
        dialog = FolderSelectDialog(pan=MagicMock())
        root = dialog._tree.topLevelItem(0)
        dialog._tree.itemClicked.emit(root, 0)
        assert dialog.selected_dir_id() == 0
        assert dialog.btn_ok.isEnabled()


class TestFolderSelectDialogMulti:
    """多选模式（复制使用）：复选框勾选收集目标目录。"""

    def test_check_root_toggles(self, qapp, no_background):
        dialog = FolderSelectDialog(pan=MagicMock(), multi_select=True)
        root = dialog._tree.topLevelItem(0)
        assert root is not None
        assert root.flags() & Qt.ItemFlag.ItemIsUserCheckable
        # 初始无勾选，确定按钮禁用
        assert dialog.selected_dir_ids() == []
        assert not dialog.btn_ok.isEnabled()

        # 勾选根目录（0）→ 收集 + 确定按钮可用
        root.setCheckState(0, Qt.CheckState.Checked)
        assert dialog.selected_dir_ids() == [0]
        assert dialog.btn_ok.isEnabled()

        # 取消勾选 → 清空 + 确定按钮禁用
        root.setCheckState(0, Qt.CheckState.Unchecked)
        assert dialog.selected_dir_ids() == []
        assert not dialog.btn_ok.isEnabled()

    def test_multi_preserves_check_order(self, qapp, no_background):
        dialog = FolderSelectDialog(pan=MagicMock(), multi_select=True)
        child_a = QTreeWidgetItem(["A"])
        child_a.setData(0, Qt.ItemDataRole.UserRole, 11)
        child_b = QTreeWidgetItem(["B"])
        child_b.setData(0, Qt.ItemDataRole.UserRole, 22)
        for child in (child_a, child_b):
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            dialog._tree.addTopLevelItem(child)

        # 按勾选顺序收集
        child_b.setCheckState(0, Qt.CheckState.Checked)
        child_a.setCheckState(0, Qt.CheckState.Checked)
        assert dialog.selected_dir_ids() == [22, 11]

        # 取消其中一个，保留另一个
        child_b.setCheckState(0, Qt.CheckState.Unchecked)
        assert dialog.selected_dir_ids() == [11]

    def test_multi_click_does_not_change_selection(self, qapp, no_background):
        """多选模式下点击条目不应改变勾选状态（勾选由复选框管理）。"""
        dialog = FolderSelectDialog(pan=MagicMock(), multi_select=True)
        root = dialog._tree.topLevelItem(0)
        dialog._tree.itemClicked.emit(root, 0)
        assert dialog.selected_dir_id() is None
        assert dialog.selected_dir_ids() == []
        assert not dialog.btn_ok.isEnabled()
