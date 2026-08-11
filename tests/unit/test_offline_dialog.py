"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.view.offline_download_dialog import OfflineDownloadDialog

_app = QApplication.instance() or QApplication([])


class TestOfflineDownloadDialog:
    def test_construct(self):
        """对话框可构建（离线下载 + 秒传导入两个标签页）。"""
        pan = MagicMock()
        dlg = OfflineDownloadDialog(pan, 0)
        assert dlg.segmentedWidget is not None
        assert dlg.offlinePage is not None
        assert dlg.rapidPage is not None
        assert dlg.urlEdit is not None
        assert dlg.rapidEdit is not None
        # 默认显示离线下载页
        assert not dlg.offlinePage.isHidden()
        assert dlg.rapidPage.isHidden()
        # 初始提交/导入按钮不可用
        assert not dlg.submitButton.isEnabled()
        assert not dlg.rapidTransferButton.isEnabled()
        dlg.deleteLater()

    def test_switch_tab(self):
        """切换到秒传导入页。"""
        pan = MagicMock()
        dlg = OfflineDownloadDialog(pan, 0)
        dlg.segmentedWidget.setCurrentItem("rapid")
        assert dlg.offlinePage.isHidden()
        assert not dlg.rapidPage.isHidden()
        dlg.deleteLater()

    def test_render_resources(self):
        """解析结果渲染到表格。"""
        pan = MagicMock()
        dlg = OfflineDownloadDialog(pan, 0)
        resources = [
            {"url": "magnet:x", "type": "magnet", "result": 0, "name": "f.iso",
             "size": 100, "id": 5, "file_nums": 0, "files": [], "err_msg": ""},
            {"url": "http://x", "type": "http", "result": 1, "name": "bad",
             "size": 0, "id": 6, "file_nums": 0, "files": [],
             "err_code": 3, "err_msg": "无法解析"},
        ]
        dlg._resources = resources
        dlg._OfflineDownloadDialog__onResolveFinished(resources, "")
        assert dlg.resourceTable.rowCount() == 2
        # 失败资源不可勾选
        assert dlg.resourceTable.item(1, 0).checkState().value == 0  # Unchecked
        # 提交按钮可用（有可下载资源）
        assert dlg.submitButton.isEnabled()
        dlg.deleteLater()

    def test_parse_rapid_updates_info(self):
        """秒传数据解析后更新信息标签并启用导入按钮。"""
        pan = MagicMock()
        pan.offline_parse_rapid.return_value = [
            {"path": "a.txt", "etag": "d41d8cd98f00b204e9800998ecf8427e", "size": 100},
        ]
        dlg = OfflineDownloadDialog(pan, 0)
        dlg.rapidEdit.setPlainText('{"files":[{"path":"a.txt",'
                                   '"etag":"d41d8cd98f00b204e9800998ecf8427e",'
                                   '"size":100}]}')
        dlg._OfflineDownloadDialog__parseRapidData()
        assert "1" in dlg.rapidInfoLabel.text()
        assert dlg.rapidTransferButton.isEnabled()
        dlg.deleteLater()
