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

from PySide6.QtWidgets import QApplication

from src.app.view.rapid_export_dialog import RapidExportDialog

_app = QApplication.instance() or QApplication([])

JSON_TEXT = (
    '{\n  "scriptVersion": "3.0.3",\n  "exportVersion": "1.0",\n'
    '  "usesBase62EtagsInExport": false,\n  "commonPath": "folder/",\n'
    '  "files": [{"path": "a.txt", "etag": "d41d8cd98f00b204e9800998ecf8427e",'
    ' "size": 100}],\n  "totalFilesCount": 1,\n  "totalSize": 100\n}'
)
LINK_TEXT = "123FLCPV2$folder/%d41d8cd98f00b204e9800998ecf8427e#100#a.txt"


class TestRapidExportDialog:
    def test_construct(self):
        """对话框可构建，默认显示链接标签。"""
        dlg = RapidExportDialog(JSON_TEXT, LINK_TEXT, 1, 100)
        assert dlg.textEdit.toPlainText() == LINK_TEXT
        assert "1" in dlg.textEdit.toPlainText()
        dlg.deleteLater()

    def test_switch_to_json(self):
        """切换到 JSON 标签显示 JSON 内容。"""
        dlg = RapidExportDialog(JSON_TEXT, LINK_TEXT, 1, 100)
        dlg.segmentedWidget.setCurrentItem("json")
        assert "commonPath" in dlg.textEdit.toPlainText()
        dlg.deleteLater()

    def test_switch_back_to_link(self):
        """切回链接标签。"""
        dlg = RapidExportDialog(JSON_TEXT, LINK_TEXT, 1, 100)
        dlg.segmentedWidget.setCurrentItem("json")
        dlg.segmentedWidget.setCurrentItem("link")
        assert dlg.textEdit.toPlainText() == LINK_TEXT
        dlg.deleteLater()

    def test_copy_link_to_clipboard(self):
        """复制链接按钮将链接写入剪贴板。"""
        dlg = RapidExportDialog(JSON_TEXT, LINK_TEXT, 1, 100)
        dlg._RapidExportDialog__copy_link()
        assert QApplication.clipboard().text() == LINK_TEXT
        dlg.deleteLater()
