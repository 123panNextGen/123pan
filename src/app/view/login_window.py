from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QFormLayout, QHBoxLayout, QDialog, QComboBox

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    MessageBox,
    TitleLabel,
)

from ..common.api import Pan123
from ..common.config import ConfigManager
from ..common.log import get_logger

logger = get_logger(__name__)


class LoginDialog(QDialog):
    """登录对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录123云盘")
        self.resize(460, 320)
        self.setFixedSize(460, 320)
        # self.setWindowFlags(
        #     self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        # )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # 标题
        title = TitleLabel()
        title.setText("欢迎使用123云盘")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        form = QFormLayout()
        form.setSpacing(15)

        # 账户选择下拉框
        self.cbo_accounts = QComboBox()
        self.cbo_accounts.setEditable(True)
        self.cbo_accounts.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cbo_accounts.lineEdit().setPlaceholderText("选择或输入账户")
        form.addRow("账户", self.cbo_accounts)

        # 密码输入框
        self.le_pass = LineEdit()
        self.le_pass.setPlaceholderText("请输入密码")
        self.le_pass.setEchoMode(LineEdit.EchoMode.Password)
        form.addRow("密码", self.le_pass)

        layout.addLayout(form)

        h = QHBoxLayout()
        h.addStretch()

        # 登录按钮
        self.btn_ok = PrimaryPushButton()
        self.btn_ok.setText("登录")
        self.btn_ok.setMinimumWidth(100)

        # 取消按钮
        self.btn_cancel = PushButton()
        self.btn_cancel.setText("取消")
        self.btn_cancel.setMinimumWidth(100)

        h.addWidget(self.btn_ok)
        h.addWidget(self.btn_cancel)
        layout.addLayout(h)

        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_cancel.clicked.connect(self.close)

        self.pan = None
        self.login_error = None

        # 从配置文件中加载已保存账户
        account_names = ConfigManager.get_account_names()
        for account_name in account_names:
            self.cbo_accounts.addItem(account_name)

        current_account = ConfigManager.get_current_account_name()
        if current_account:
            if self.cbo_accounts.findText(current_account) >= 0:
                self.cbo_accounts.setCurrentText(current_account)
            else:
                self.cbo_accounts.addItem(current_account)
                self.cbo_accounts.setCurrentText(current_account)

        self.cbo_accounts.currentTextChanged.connect(self.on_account_selected)
        self.on_account_selected(self.cbo_accounts.currentText())

    def on_account_selected(self, account_name):
        """切换账户时加载保存的信息"""
        account_name = account_name.strip()
        if not account_name:
            return
        account = ConfigManager.get_account(account_name)
        if account:
            self.le_pass.setText(account.get("passWord", ""))

    def on_ok(self):
        """登录处理"""

        user = self.cbo_accounts.currentText().strip()
        pwd = self.le_pass.text()
        if not user or not pwd:
            MessageBox("提示", "请输入用户名和密码。", self).exec()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            account = ConfigManager.get_account(user)
            if account:
                # 有保存账户信息时，优先读取该账户的设备信息和授权信息
                self.pan = Pan123(readfile=True, user_name=user, password=pwd)
            else:
                # 新账户登录，不读取旧账号信息
                self.pan = Pan123(readfile=False, user_name=user, password=pwd)

            # 无论是否换账号，都尝试登录以确保 authorization 有效
            code = self.pan.login()
            if code != 200 and code != 0:
                self.login_error = f"登录失败，返回码: {code}"
                QApplication.restoreOverrideCursor()
                MessageBox("登录失败", self.login_error, self).exec()
                return
        except Exception as e:
            self.login_error = str(e)
            QApplication.restoreOverrideCursor()
            MessageBox("登录异常", "登录时发生异常:\n" + str(e), self).exec()
            return
        finally:
            QApplication.restoreOverrideCursor()

        try:
            if hasattr(self.pan, "save_file"):
                self.pan.save_file()
        except (IOError, OSError) as e:
            # 忽略配置文件保存失败,不影响登录流程
            logger.warning(f"保存配置失败: {e}")
        except Exception as e:
            logger.error(f"保存配置时发生未知错误: {e}")
        self.accept()

    def get_pan(self):
        """获取登录成功的Pan对象"""
        return self.pan
