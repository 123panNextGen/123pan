"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QTreeWidget

from qfluentwidgets import TableWidget

from src.app.view.file_table import FileTableManager, format_date_text
from src.app.view.file_tree import FileTreeManager


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _sample_items():
    return [
        {"FileId": 1, "FileName": "bbb.txt", "Type": 0, "Size": 100,
         "UpdateAt": 1700000000},
        {"FileId": 2, "FileName": "文件夹A", "Type": 1, "Size": 0,
         "UpdateAt": 1700000100},
        {"FileId": 3, "FileName": "aaa.jpg", "Type": 0, "Size": 50,
         "UpdateAt": 1700000200},
    ]


class TestFileTableManager:
    def test_render_rows(self, qapp):
        table = TableWidget()
        table.setColumnCount(4)
        mgr = FileTableManager(table, QLabel())
        mgr.set_items(_sample_items())
        assert table.rowCount() == 3
        # 原序渲染：不排序
        assert table.item(0, 0).text() == "bbb.txt"
        # 数据缓存与索引
        assert len(mgr.current_items) == 3
        assert mgr.find_by_id(2)["FileName"] == "文件夹A"
        assert mgr.find_by_id(999) is None

    def test_sort_folders_first(self, qapp):
        table = TableWidget()
        table.setColumnCount(4)
        mgr = FileTableManager(table, QLabel())
        mgr.sort_mode = FileTableManager.SORT_NAME
        mgr.sort_ascending = True
        mgr.set_items(mgr.sort(_sample_items()))
        assert table.item(0, 0).text() == "文件夹A"
        assert table.item(1, 0).text() == "aaa.jpg"
        assert table.item(2, 0).text() == "bbb.txt"

    def test_sort_by_size(self, qapp):
        table = TableWidget()
        table.setColumnCount(4)
        mgr = FileTableManager(table, QLabel())
        mgr.sort_mode = FileTableManager.SORT_SIZE
        mgr.sort_ascending = False
        sorted_items = mgr.sort(_sample_items())
        # 文件按大小降序：bbb.txt(100) > aaa.jpg(50)
        assert sorted_items[1]["FileName"] == "bbb.txt"
        assert sorted_items[2]["FileName"] == "aaa.jpg"

    def test_search_filter(self, qapp):
        table = TableWidget()
        table.setColumnCount(4)
        mgr = FileTableManager(table, QLabel())
        mgr.set_items(_sample_items())
        mgr.search_text = "aaa"
        mgr.apply_search(False)
        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "aaa.jpg"
        # 清空搜索恢复完整列表
        mgr.search_text = ""
        mgr.apply_search(False)
        assert table.rowCount() == 3
        # 过滤不覆盖完整缓存
        assert len(mgr.current_items) == 3

    def test_empty_state(self, qapp):
        table = TableWidget()
        table.setColumnCount(4)
        label = QLabel()
        mgr = FileTableManager(table, label)
        mgr.set_items([])
        mgr.update_state(0, False)
        assert not label.isHidden()  # 空文件夹提示
        mgr.update_state(5, False)
        assert label.isHidden()  # 有内容隐藏提示

    def test_format_date(self):
        # 非零时间戳返回 YYYY-MM-DD HH:MM 格式
        assert len(format_date_text(1700000000)) == 16
        assert format_date_text(1700000000)[4] == "-"
        assert format_date_text(0) == ""
        assert format_date_text(None) == ""


class TestFileTreeManager:
    def test_init_tree(self, qapp):
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        root = mgr.find_item(0)
        assert root is not None
        assert root.text(0) == "根目录"
        # 根节点含占位符
        assert root.childCount() == 1

    def test_update_folders_adds_children(self, qapp):
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [
            {"FileId": 10, "FileName": "子目录"},
            {"FileId": 11, "FileName": "另一个"},
        ])
        assert mgr.find_item(10) is not None
        assert mgr.find_item(11).text(0) == "另一个"
        assert mgr.find_item(999) is None

    def test_update_folders_skips_existing(self, qapp):
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [{"FileId": 10, "FileName": "子目录"}])
        root = mgr.find_item(0)
        count_after_first = root.childCount()
        mgr.update_folders(0, [{"FileId": 10, "FileName": "子目录"}])
        assert root.childCount() == count_after_first

    def test_build_path_stack(self, qapp):
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [{"FileId": 10, "FileName": "子目录"}])
        child = mgr.find_item(10)
        assert mgr.build_path_stack(child) == [(0, "根目录"), (10, "子目录")]

    def test_lazy_load(self, qapp):
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [{"FileId": 10, "FileName": "子目录"}])
        child = mgr.find_item(10)

        def fake_loader(dir_id, item):
            mgr.on_folder_loaded(
                item, dir_id,
                [{"FileId": 20, "FileName": "孙目录", "Type": 1}], "",
            )

        mgr.ensure_loaded(child, fake_loader)
        assert mgr.find_item(20) is not None
        # 已加载节点再次触发不会重复加载
        loader_called = []
        mgr.ensure_loaded(child, lambda d, i: loader_called.append(d))
        assert loader_called == []
