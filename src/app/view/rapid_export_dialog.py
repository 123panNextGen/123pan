"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    InfoBar,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
)

from ..common.i18n import tr
from ..common.utils import format_file_size


class RapidExportDialog(QDialog):
    """秒传数据导出对话框（文本链接 / JSON 双标签）。

    展示生成的秒传数据，支持复制到剪贴板或导出为 JSON 文件。
    """

    def __init__(self, json_text, link_text, file_count, total_size, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(tr("rapid.export_title", "生成秒传"))
        self.resize(620, 520)
        self._json_text = json_text
        self._link_text = link_text

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 16, 20, 16)
        self.mainLayout.setSpacing(10)

        summary = QLabel(
            tr("rapid.export_summary", "共 {} 个文件，{}").format(
                file_count, format_file_size(total_size)
            ),
            self,
        )
        summary.setStyleSheet("color: gray;")
        self.mainLayout.addWidget(summary)

        self.segmentedWidget = SegmentedWidget(self)
        self.segmentedWidget.addItem(
            routeKey="link", icon=FIF.LINK.icon(),
            text=tr("rapid.tab_link", "秒传链接"),
        )
        self.segmentedWidget.addItem(
            routeKey="json", icon=FIF.DOCUMENT.icon(),
            text=tr("rapid.tab_json", "秒传 JSON"),
        )
        self.segmentedWidget.setCurrentItem("link")
        self.mainLayout.addWidget(self.segmentedWidget)

        self.textEdit = QTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(link_text)
        self.textEdit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.mainLayout.addWidget(self.textEdit, 1)

        hint = QLabel(
            tr("rapid.export_hint",
               "将秒传数据分享给他人，对方可在 123pan 的「离线下载 → 秒传导入」中直接导入"),
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        self.mainLayout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.copyLinkButton = PushButton(
            FIF.COPY.icon(), tr("rapid.copy_link", "复制链接"), self
        )
        self.copyLinkButton.clicked.connect(self.__copy_link)
        btn_row.addWidget(self.copyLinkButton)

        self.copyJsonButton = PushButton(
            FIF.COPY.icon(), tr("rapid.copy_json", "复制 JSON"), self
        )
        self.copyJsonButton.clicked.connect(self.__copy_json)
        btn_row.addWidget(self.copyJsonButton)

        self.saveJsonButton = PushButton(
            FIF.SAVE.icon(), tr("rapid.save_json", "导出 JSON 文件"), self
        )
        self.saveJsonButton.clicked.connect(self.__save_json)
        btn_row.addWidget(self.saveJsonButton)

        self.closeButton = PrimaryPushButton(
            tr("rapid.close", "关闭"), self
        )
        self.closeButton.clicked.connect(self.accept)
        btn_row.addWidget(self.closeButton)
        self.mainLayout.addLayout(btn_row)

        self.segmentedWidget.currentItemChanged.connect(self.__onSegmentChanged)

    def __onSegmentChanged(self, route_key):
        if route_key == "json":
            self.textEdit.setPlainText(self._json_text)
        else:
            self.textEdit.setPlainText(self._link_text)

    def __copy_link(self):
        QApplication.clipboard().setText(self._link_text)
        InfoBar.success(
            title=tr("rapid.msg_copied", "已复制"),
            content=tr("rapid.msg_link_copied", "秒传链接已复制到剪贴板"),
            parent=self,
        )

    def __copy_json(self):
        QApplication.clipboard().setText(self._json_text)
        InfoBar.success(
            title=tr("rapid.msg_copied", "已复制"),
            content=tr("rapid.msg_json_copied", "秒传 JSON 已复制到剪贴板"),
            parent=self,
        )

    def __save_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("rapid.save_json", "导出 JSON 文件"),
            str(Path.home() / "rapid_transfer.json"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            # 格式化输出，便于阅读
            data = json.loads(self._json_text)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            InfoBar.success(
                title=tr("rapid.msg_saved", "已导出"),
                content=tr("rapid.msg_json_saved", "秒传 JSON 已保存到 {}").format(path),
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                title=tr("rapid.msg_save_failed", "导出失败"),
                content=str(e),
                parent=self,
            )
