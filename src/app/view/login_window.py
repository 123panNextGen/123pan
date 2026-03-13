from PyQt6.QtCore import Qt, pyqtSignal, QEasingCurve, QUrl, QSize, QTimer
from PyQt6.QtGui import QIcon, QDesktopServices, QColor
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QFrame, QWidget, QDialog, QMessageBox, QVBoxLayout, QFormLayout, QLineEdit, QPushButton

from qfluentwidgets import (NavigationAvatarWidget, NavigationItemPosition, MessageBox, FluentWindow,
                            SplashScreen, SystemThemeListener, isDarkTheme)
from qfluentwidgets import FluentIcon as FIF

from ..common.api import Pan123


class LoginDialog(FluentWindow):
    """登录对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录123云盘")
        self.setModal(True)
        self.resize(420, 150)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.le_user = QLineEdit()
        self.le_pass = QLineEdit()
        self.le_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("用户名：", self.le_user)
        form.addRow("密码：", self.le_pass)
        layout.addLayout(form)

        h = QHBoxLayout()
        h.addStretch()
        self.btn_ok = QPushButton("登录")
        self.btn_cancel = QPushButton("取消")
        h.addWidget(self.btn_ok)
        h.addWidget(self.btn_cancel)
        layout.addLayout(h)

        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_cancel.clicked.connect(self.reject)

        self.pan = None
        self.login_error = None

        # 从配置文件中加载用户名
        config = config.ConfigManager.load_config()
        self.le_user.setText(config.get("userName", ""))

    def on_ok(self):
        """登录处理"""
        
        user = self.le_user.text().strip()
        pwd = self.le_pass.text()
        if not user or not pwd:
            MessageBox.information(self, "提示", "请输入用户名和密码。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # 构造123pan并登录
            try:
                self.pan = Pan123(readfile=False, user_name=user, pass_word=pwd, input_pwd=False)
            except Exception:
                self.pan = Pan123(readfile=False, user_name=user, pass_word=pwd, input_pwd=False)
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