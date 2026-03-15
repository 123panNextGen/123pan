from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QDialog

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    BodyLabel,
)


class NewFolderDialog(QDialog):
    """新建文件夹弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建文件夹")
        self.resize(400, 180)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # 标题
        title = TitleLabel("新建文件夹")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        # 提示信息
        hint = BodyLabel("请输入文件夹名称")
        layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)

        # 输入框
        self.name_input = LineEdit()
        self.name_input.setText("新建文件夹")
        self.name_input.selectAll()
        layout.addWidget(self.name_input)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # 取消按钮
        cancel_button = PushButton("取消")
        cancel_button.setMinimumWidth(100)
        cancel_button.clicked.connect(self.reject)

        # 确定按钮
        ok_button = PrimaryPushButton("确定")
        ok_button.setMinimumWidth(100)
        ok_button.clicked.connect(self.accept)

        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

    def get_new_name(self):
        """获取新名称"""
        return self.name_input.text().strip()
