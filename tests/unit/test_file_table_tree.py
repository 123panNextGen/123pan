"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QLabel, QTreeWidget

from qfluentwidgets import TableWidget

from src.app.view.file_table import FileTableManager, format_date_text
from src.app.view.file_tree import FileTreeManager
from src.app.api.model import ApiCode, ApiReturnModel
from src.app.tasks.file_tasks import CheckDownloadTrafficTask
from src.app.tasks.signals import _DownloadTrafficSignals


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

    def test_name_tooltip(self, qapp):
        """名称单元格悬停提示完整文件名（长名截断时可查看）。"""
        table = TableWidget()
        table.setColumnCount(4)
        mgr = FileTableManager(table, QLabel())
        long_name = "这是一个非常长的文件名用来测试悬停提示功能是否正常工作" * 3
        mgr.set_items([{"FileId": 1, "FileName": long_name, "Type": 0,
                        "Size": 100, "UpdateAt": 1700000000}])
        item = table.item(0, 0)
        assert item.toolTip() == long_name

    def test_name_column_interactive(self, qapp):
        """文件表格名称列允许用户手动调整宽度。"""
        from PySide6.QtWidgets import QHeaderView
        from src.app.view.file_interface import FileInterface

        panel = FileInterface()
        header = panel.fileTable.horizontalHeader()
        assert header is not None
        assert (
            header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
        )
        # 默认宽度为 320
        assert header.sectionSize(0) == 320
        panel.deleteLater()

    def test_drag_drop_handlers_not_shadowed_by_qwidget(self, qapp):
        """回归：FileActionsMixin 的拖拽事件不得被 QWidget 内建方法遮蔽。

        PySide6 的 QWidget 暴露了 C++ 虚拟方法 dragEnterEvent/dragMoveEvent/
        dropEvent（默认忽略事件）。若 FileInterface 基类顺序为
        (QWidget, FileActionsMixin)，MRO 会命中 QWidget 的实现，
        导致拖拽上传完全失效。FileActionsMixin 必须排在 QWidget 之前。
        """
        from src.app.view.file_actions import FileActionsMixin
        from src.app.view.file_interface import FileInterface

        assert FileInterface.dragEnterEvent == FileActionsMixin.dragEnterEvent
        assert FileInterface.dragMoveEvent == FileActionsMixin.dragMoveEvent
        assert FileInterface.dropEvent == FileActionsMixin.dropEvent

    def test_download_traffic_confirmation(self, qapp, mocker):
        from src.app.view.file_interface import FileInterface

        panel = FileInterface()
        panel._download_traffic_checking = True
        panel.downloadButton.setEnabled(False)
        items = [
            {"file_id": 42, "file_name": "demo.bin", "file_size": 1024**3}
        ]
        message_box = mocker.patch("src.app.view.file_actions.MessageBox")
        message_box.return_value.exec.return_value = True
        queue_downloads = mocker.patch.object(panel, "_queueDownloadItems")

        panel._onDownloadTrafficChecked(
            {
                "originalRemainTraffic": 5 * 1024**3,
                "originalFileSize": 1024**3,
                "clientFileSize": 512 * 1024**2,
                "isTrafficExceeded": False,
                "isBlocked": False,
            },
            "",
            items,
        )

        content = message_box.call_args.args[1]
        assert "5.0 GB" in content
        assert "1.0 GB" in content
        assert "4.0 GB" in content
        assert "-1.0 GB" not in content
        assert "512.0 MB" in content
        assert panel.downloadButton.isEnabled()
        queue_downloads.assert_called_once_with(items)
        panel.deleteLater()

    def test_download_traffic_confirmation_handles_negative_remaining(self, qapp, mocker):
        from src.app.view.file_interface import FileInterface

        panel = FileInterface()
        message_box = mocker.patch("src.app.view.file_actions.MessageBox")
        message_box.return_value.exec.return_value = False

        panel._onDownloadTrafficChecked(
            {
                "originalRemainTraffic": 492 * 1024**2,
                "originalFileSize": 14 * 1024**3,
                "clientFileSize": 7 * 1024**3,
                "isTrafficExceeded": False,
                "isBlocked": False,
            },
            "",
            [{"file_id": 42, "file_name": "demo.bin", "file_size": 14 * 1024**3}],
        )

        content = message_box.call_args.args[1]
        assert "下载后预计剩余原始流量：-13.52 GB" in content
        assert "本次下载预计会超出剩余流量。" in content
        panel.deleteLater()

    def test_vip_download_skips_traffic_check(self, qapp):
        pan = SimpleNamespace(
            get_user_info=lambda: ApiReturnModel(
                code=0, api_code=0, api_code_enum=ApiCode.success, msg="",
                data=SimpleNamespace(vip=True),
            ),
            check_download_traffic=lambda _: (_ for _ in ()).throw(
                AssertionError("VIP 不应调用流量检查接口")
            ),
        )
        received = []
        signals = _DownloadTrafficSignals()
        signals.finished.connect(lambda data, error: received.append((data, error)))

        CheckDownloadTrafficTask(pan, [42], signals).run()

        assert received == [({"unlimited": True}, "")]

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

    def test_update_folders_removes_deleted(self, qapp):
        """删除后目录树必须移除服务器上已不存在的文件夹节点。"""
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [
            {"FileId": 10, "FileName": "子目录"},
            {"FileId": 11, "FileName": "将被删除"},
        ])
        assert mgr.find_item(11) is not None

        # 第二次刷新：11 已不在列表中（删除场景）
        mgr.update_folders(0, [{"FileId": 10, "FileName": "子目录"}])
        assert mgr.find_item(10) is not None
        assert mgr.find_item(11) is None
        assert mgr.find_item(0).childCount() == 1  # 仅剩占位符 + 子目录

    def test_update_folders_removes_only_gone(self, qapp):
        """仅移除消失的节点，保留其余节点。"""
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [
            {"FileId": 10, "FileName": "保留"},
            {"FileId": 11, "FileName": "删除A"},
            {"FileId": 12, "FileName": "删除B"},
        ])
        mgr.update_folders(0, [{"FileId": 10, "FileName": "保留"}])
        assert mgr.find_item(10) is not None
        assert mgr.find_item(11) is None
        assert mgr.find_item(12) is None

    def test_update_folders_renames_existing(self, qapp):
        """重命名后目录树节点文本同步更新。"""
        mgr = FileTreeManager(QTreeWidget())
        mgr.init_tree()
        mgr.update_folders(0, [{"FileId": 10, "FileName": "旧名字"}])
        mgr.update_folders(0, [{"FileId": 10, "FileName": "新名字"}])
        assert mgr.find_item(10).text(0) == "新名字"

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
