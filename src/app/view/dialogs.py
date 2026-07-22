"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QDialog

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
