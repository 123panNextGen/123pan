from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from qfluentwidgets import (
    FluentIcon as FIF,
    SettingCardGroup,
    PushSettingCard,
    SettingCard,
)


def _mask_username(username):
    """如果用户名类似手机号，隐藏中间4位"""
    if not username:
        return ""

    # 检查是否为11位数字（手机号格式）
    if len(username) == 11 and username.isdigit():
        return f"{username[:3]}****{username[7:]}"

    return username


class CloudInterface(QWidget):
    """云盘页面"""

    # 定义退出登录信号
    logoutRequested = pyqtSignal()
    switchAccountRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.pan = None
        self.setObjectName("CloudInterface")

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        # 添加标题
        title_label = QLabel("云盘信息")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        self.mainLayout.addWidget(title_label)

        # 创建设置卡片组
        self.accountGroup = SettingCardGroup("账户信息", self)

        # 添加用户名显示（使用SettingCard样式）
        self.username_card = SettingCard(
            FIF.PEOPLE,
            "账户",
            "当前登录的账户信息",
            self.accountGroup
        )
        self.username_label = QLabel()
        font = QFont()
        font.setPointSize(12)
        self.username_label.setFont(font)
        self.username_card.hBoxLayout.addWidget(self.username_label, 0, Qt.AlignmentFlag.AlignRight)
        self.username_card.hBoxLayout.addSpacing(16)
        self.accountGroup.addSettingCard(self.username_card)

        # 添加切换账号卡片
        self.switch_card = PushSettingCard(
            "切换账号",
            FIF.SYNC,
            "切换登录账号",
            "从已保存账号或新账号登录",
            self.accountGroup,
        )
        self.switch_card.clicked.connect(self.switchAccountRequested.emit)
        self.accountGroup.addSettingCard(self.switch_card)

        # 添加退出登录卡片
        self.logout_card = PushSettingCard(
            "退出登录",
            FIF.CLOSE,
            "退出登录",
            "退出当前登录的账户",
            self.accountGroup,
        )
        self.logout_card.clicked.connect(self.logoutRequested.emit)
        self.accountGroup.addSettingCard(self.logout_card)

        # 将设置卡片组添加到主布局
        self.mainLayout.addWidget(self.accountGroup)

        self.mainLayout.addStretch()

    def set_pan(self, pan):
        """设置Pan123实例并更新用户信息"""
        self.pan = pan
        if self.pan and hasattr(self.pan, 'user_name'):
            username = _mask_username(self.pan.user_name)
            self.username_label.setText(f"用户名: {username}")
