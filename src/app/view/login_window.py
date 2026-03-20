from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QFormLayout, QHBoxLayout, QDialog

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    MessageBox,
    TitleLabel,
)

from ..common.api import Pan123
from ..common.config import ConfigManager


class LoginDialog(QDialog):
    """登录对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录123云盘")
        self.resize(460, 320)
        self.setFixedSize(460, 320)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # 标题
        title = TitleLabel("欢迎使用123云盘")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        form = QFormLayout()
        form.setSpacing(15)

        # 用户名输入框
        self.le_user = LineEdit()
        self.le_user.setPlaceholderText("请输入用户名")
        form.addRow("用户名", self.le_user)

        # 密码输入框
        self.le_pass = LineEdit()
        self.le_pass.setPlaceholderText("请输入密码")
        self.le_pass.setEchoMode(LineEdit.EchoMode.Password)
        form.addRow("密码", self.le_pass)

        layout.addLayout(form)

        h = QHBoxLayout()
        h.addStretch()

        # 登录按钮
        self.btn_ok = PrimaryPushButton("登录")
        self.btn_ok.setMinimumWidth(100)

        # 取消按钮
        self.btn_cancel = PushButton("取消")
        self.btn_cancel.setMinimumWidth(100)

        h.addWidget(self.btn_ok)
        h.addWidget(self.btn_cancel)
        layout.addLayout(h)

        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_cancel.clicked.connect(self.close)

        self.pan = None
        self.login_error = None

        # 从配置文件中加载用户名
        config = ConfigManager.load_config()
        self.le_user.setText(config.get("userName", ""))
        self.le_pass.setText(config.get("passWord", ""))

    def on_ok(self):
        """登录处理"""

        user = self.le_user.text().strip()
        pwd = self.le_pass.text()
        if not user or not pwd:
            MessageBox.information(self, "提示", "请输入用户名和密码。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # 构造123pan并登录（优先读取已保存的设备信息，避免每次创建新设备）
            try:
                self.pan = Pan123(readfile=True, input_pwd=False)
            except Exception:
                self.pan = Pan123(readfile=True, input_pwd=False)

            # 覆盖用户名/密码（配置文件可能保存了旧账号）
            self.pan.user_name = user
            self.pan.password = pwd

            if not getattr(self.pan, "authorization", None):
                code = self.pan.login()
                if code != 200 and code != 0:
                    self.login_error = f"登录失败，返回码: {code}"
                    QApplication.restoreOverrideCursor()
                    MessageBox.critical(self, "登录失败", self.login_error)
                    return
        except Exception as e:
            self.login_error = str(e)
            QApplication.restoreOverrideCursor()
            MessageBox.critical(self, "登录异常", "登录时发生异常:\n" + str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()

        try:
            if hasattr(self.pan, "save_file"):
                self.pan.save_file()
        except Exception:
            pass
        self.accept()

    def get_pan(self):
        """获取登录成功的Pan对象"""
        return self.pan
