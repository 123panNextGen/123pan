import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import requests
from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    MessageBox,
    SegmentedWidget,
)

from ..common.api import Pan123
from ..common.database import Database
from ..common.log import get_logger
from .qr_login_page import QRLoginPage

logger = get_logger(__name__)


def has_saved_credentials(db):
    user_name = (db.get_config("userName", "") or "").strip()
    pass_word = db.get_config("passWord", "") or ""
    return bool(user_name and pass_word)


def login_with_credentials(user, pwd):
    pan = Pan123(readfile=False, user_name=user, password=pwd)
    code = pan.login()
    if code not in {0, 200}:
        raise RuntimeError(f"登录失败，返回码: {code}")
    return pan


def try_token_probe(db):
    """用已有 token 调 user_info API 探测有效性。
    成功返回 Pan123 对象，失败返回 None。
    """
    token = db.get_config("authorization", "")
    if not token:
        return None
    try:
        pan = Pan123(readfile=True, user_name="", password="", authorization=token)
        user_data = pan.user_info()
        if user_data is not None:
            logger.info("Token 探测成功，跳过登录")
            return pan
        logger.warning("Token 探测失败：user_info 未返回有效用户数据")
        db.set_config("authorization", "")
        return None
    except Exception as exc:
        logger.warning(f"Token 探测异常: {exc}")
    return None


class LoginDialog(QDialog):
    """登录对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录123云盘")
        self._password_size = (345, 320)
        self._qr_size = (391, 400)
        self.setFixedSize(*self._password_size)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        # Tab 切换
        self.segmented_widget = SegmentedWidget()
        self.segmented_widget.addItem(routeKey="password", text="密码登录")
        self.segmented_widget.addItem(routeKey="qrcode", text="扫码登录")
        self.segmented_widget.setCurrentItem("password")
        layout.addWidget(self.segmented_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        # 页面容器
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)

        # -- 密码登录页面 (page 0) --
        password_page = QWidget()
        password_layout = QVBoxLayout(password_page)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(0)

        # 用户名输入框
        self.le_user = LineEdit()
        self.le_user.setPlaceholderText("请输入用户名")
        password_layout.addWidget(self.le_user)

        password_layout.addSpacing(15)

        # 密码输入框
        self.le_pass = LineEdit()
        self.le_pass.setPlaceholderText("请输入密码")
        self.le_pass.setEchoMode(LineEdit.EchoMode.Password)
        password_layout.addWidget(self.le_pass)

        password_layout.addSpacing(12)

        # 记住密码 / 保持登录
        self.cb_remember_password = QCheckBox("记住密码")
        self.cb_stay_logged_in = QCheckBox("保持登录")
        checkbox_layout = QHBoxLayout()
        checkbox_layout.addWidget(self.cb_remember_password)
        checkbox_layout.addStretch()
        checkbox_layout.addWidget(self.cb_stay_logged_in)
        password_layout.addLayout(checkbox_layout)

        password_layout.addSpacing(20)

        # 登录 / 取消按钮
        h = QHBoxLayout()
        self.btn_ok = PrimaryPushButton("登录")
        self.btn_ok.setMinimumWidth(100)
        self.btn_cancel = PushButton("取消")
        self.btn_cancel.setMinimumWidth(100)
        h.addWidget(self.btn_ok)
        h.addStretch()
        h.addWidget(self.btn_cancel)
        password_layout.addLayout(h)

        self.stacked_widget.addWidget(password_page)

        # -- 扫码登录页面 (page 1) --
        self.qr_page = QRLoginPage(parent=self)
        self.qr_page.loginSuccess.connect(self._on_qr_login_success)
        self.stacked_widget.addWidget(self.qr_page)

        # 同步两页面的 "保持登录" checkbox 状态
        self.cb_stay_logged_in.stateChanged.connect(
            lambda state: self.qr_page.cb_stay_logged_in.setChecked(bool(state))
        )
        self.qr_page.cb_stay_logged_in.stateChanged.connect(
            lambda state: self.cb_stay_logged_in.setChecked(bool(state))
        )

        # 信号连接
        self.segmented_widget.currentItemChanged.connect(self._on_tab_changed)
        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_cancel.clicked.connect(self.close)

        self.pan = None
        self.login_error = None

        # 从配置文件中加载用户名
        db = Database.instance()
        remember_password = bool(db.get_config("rememberPassword", False))
        self.le_user.setText(db.get_config("userName", ""))
        self.le_pass.setText(db.get_config("passWord", "") if remember_password else "")
        self.cb_remember_password.setChecked(remember_password)
        self.cb_stay_logged_in.setChecked(bool(db.get_config("stayLoggedIn", True)))
        self.cb_remember_password.stateChanged.connect(self._on_remember_password_changed)

    def _on_remember_password_changed(self, state):
        if not state:
            Database.instance().set_config("passWord", "")

    def _on_tab_changed(self, route_key):
        if route_key == "password":
            self.stacked_widget.setCurrentIndex(0)
            self.qr_page.stop_polling()
            self.setFixedSize(*self._password_size)
        else:
            self.stacked_widget.setCurrentIndex(1)
            self.setFixedSize(*self._qr_size)
            self.qr_page.start_qr_flow()

    def _on_qr_login_success(self, pan_object):
        """QR 登录成功回调。"""
        self.pan = pan_object
        try:
            db = Database.instance()
            db.set_config("userName", pan_object.user_name)
            db.set_config("passWord", "")
            db.set_config("rememberPassword", False)
            if self.cb_stay_logged_in.isChecked():
                db.set_config("authorization", pan_object.authorization)
            else:
                db.set_config("authorization", "")
            db.set_config("stayLoggedIn", self.cb_stay_logged_in.isChecked())
            db.set_config("deviceType", pan_object.devicetype)
            db.set_config("osVersion", pan_object.osversion)
            db.set_config("loginuuid", pan_object.loginuuid)
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")
        self.accept()

    def on_ok(self):
        """登录处理"""

        user = self.le_user.text().strip()
        pwd = self.le_pass.text()
        if not user or not pwd:
            MessageBox("提示", "请输入用户名和密码。", self).exec()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.pan = login_with_credentials(user, pwd)
        except requests.exceptions.ConnectTimeout as e:
            self.login_error = f"连接超时，服务器无响应: {e}"
            logger.error(self.login_error, exc_info=True)
            MessageBox("登录失败", self.login_error, self).exec()
            return
        except requests.exceptions.ReadTimeout as e:
            self.login_error = f"读取超时，服务器响应过慢: {e}"
            logger.error(self.login_error, exc_info=True)
            MessageBox("登录失败", self.login_error, self).exec()
            return
        except requests.exceptions.ConnectionError as e:
            self.login_error = f"网络连接失败，请检查网络: {e}"
            logger.error(self.login_error, exc_info=True)
            MessageBox("登录失败", self.login_error, self).exec()
            return
        except requests.exceptions.RequestException as e:
            self.login_error = f"请求异常: {e}"
            logger.error(self.login_error, exc_info=True)
            MessageBox("登录失败", self.login_error, self).exec()
            return
        except RuntimeError as e:
            self.login_error = str(e)
            logger.error(self.login_error)
            MessageBox("登录失败", self.login_error, self).exec()
            return
        except Exception as e:
            self.login_error = f"登录时发生未知异常: {type(e).__name__}: {e}"
            logger.error(
                "登录异常:\n%s", traceback.format_exc()
            )
            MessageBox("登录异常", self.login_error, self).exec()
            return
        finally:
            QApplication.restoreOverrideCursor()

        try:
            db = Database.instance()
            # 始终保存 userName 和设备信息
            db.set_config("userName", user)
            db.set_config("deviceType", self.pan.devicetype)
            db.set_config("osVersion", self.pan.osversion)
            db.set_config("loginuuid", self.pan.loginuuid)

            # 按用户选择保存密码
            if self.cb_remember_password.isChecked():
                db.set_config("passWord", pwd)
            else:
                db.set_config("passWord", "")

            # 按用户选择保存 token
            if self.cb_stay_logged_in.isChecked():
                db.set_config("authorization", self.pan.authorization)
            else:
                db.set_config("authorization", "")

            # 保存 checkbox 状态
            db.set_config("rememberPassword", self.cb_remember_password.isChecked())
            db.set_config("stayLoggedIn", self.cb_stay_logged_in.isChecked())
        except (IOError, OSError) as e:
            logger.warning(f"保存配置失败: {e}")
        except Exception as e:
            logger.error(f"保存配置时发生未知错误: {e}")
        self.accept()

    def get_pan(self):
        """获取登录成功的Pan对象"""
        return self.pan
