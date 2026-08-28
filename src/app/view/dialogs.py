"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QDialog, QLabel

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    BodyLabel,
)

from ..common.i18n import tr


class InputDialog(QDialog):
    """通用文本输入弹窗（取代 NewFolderDialog 和 RenameDialog）。"""

    def __init__(self, title, hint, default_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(400, 180)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        title_label = TitleLabel(title)
        layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        hint_label = BodyLabel(hint)
        layout.addWidget(hint_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._input = LineEdit()
        self._input.setText(default_text)
        self._input.selectAll()
        self._input.returnPressed.connect(self.accept)
        layout.addWidget(self._input)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = PushButton(tr("dialog.cancel", "取消"))
        cancel_button.setMinimumWidth(100)
        cancel_button.clicked.connect(self.reject)

        ok_button = PrimaryPushButton(tr("dialog.ok", "确定"))
        ok_button.setMinimumWidth(100)
        ok_button.clicked.connect(self.accept)

        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

    def get_input_text(self):
        return self._input.text().strip()


class DuplicateFileDialog(QDialog):
    """同名文件处理弹窗。"""

    def __init__(self, file_name, conflict_info, file_size, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(tr("transfer.duplicate_title", "检测到同名文件"))
        self.setMinimumWidth(460)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel(self.windowTitle()))
        layout.addWidget(QLabel(
            tr("transfer.duplicate_message", "文件 '{}' 已存在，请选择处理方式").format(file_name)
        ))

        updated_at = conflict_info.get("updated_at", tr("transfer.duplicate_unknown", "未知"))
        existing_size = conflict_info.get("size", file_size)
        etag = conflict_info.get("etag", tr("transfer.duplicate_unknown", "未知"))
        details = tr(
            "transfer.duplicate_details",
            "文件时间：{}\n文件大小：{}\nMD5：{}",
        ).format(updated_at, self._format_size(existing_size), etag)
        layout.addWidget(BodyLabel(details))

        buttons = QHBoxLayout()
        cancel = PushButton(tr("dialog.cancel", "取消"))
        overwrite = PushButton(tr("transfer.duplicate_overwrite", "覆盖（替换）"))
        keep = PrimaryPushButton(tr("transfer.duplicate_keep", "保留两者"))
        cancel.clicked.connect(self.reject)
        overwrite.clicked.connect(lambda: self._accept_choice(2))
        keep.clicked.connect(lambda: self._accept_choice(1))
        buttons.addWidget(cancel)
        buttons.addWidget(overwrite)
        buttons.addWidget(keep)
        layout.addLayout(buttons)

    @staticmethod
    def _format_size(size):
        size = float(size or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024

    def _accept_choice(self, choice):
        self.choice = choice
        self.accept()
