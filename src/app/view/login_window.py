"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QDialog,
    QComboBox,
    QStackedWidget,
    QWidget,
)

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    MessageBox,
    TitleLabel,
    SegmentedWidget,
    CheckBox,
)

from ..common.config import ConfigManager
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import PasswordLoginTask, connect_tracked
from ..tasks.signals import _PasswordLoginSignals
from .qr_login_page import QRLoginPage

logger = get_logger(__name__)


def user_name_of(pan):
    """安全获取 Pan123 实例的用户名。"""
    return pan.user_name if hasattr(pan, "user_name") else "?"


class LoginDialog(QDialog):
    """登录对话框"""

    # noinspection PyUnresolvedReferences
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("login.title", "登录123云盘"))
        # 使用最小尺寸替代固定尺寸，兼容高 DPI 显示器
        # 高度需容纳二维码页面（200px 二维码 + 状态 + 复选框），
        # 过小会导致布局压缩时二维码与下方状态文字重叠。
        self.setMinimumSize(420, 480)
        self.resize(480, 500)
        logger.debug("LoginDialog 初始化")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        # 标题
        title = TitleLabel()
        title.setText(tr("login.welcome", "欢迎使用123云盘"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 登录方式切换
        self.segmented_widget = SegmentedWidget()
        self.segmented_widget.addItem(
            routeKey="password", text=tr("login.tab_password", "密码登录")
        )
        self.segmented_widget.addItem(
            routeKey="qrcode", text=tr("login.tab_qr", "扫码登录")
        )
        self.segmented_widget.setCurrentItem("password")
        layout.addWidget(
            self.segmented_widget, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # 页面容器
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)

        # -- 密码登录页面 (page 0) --
        password_page = QWidget()
        p_layout = QVBoxLayout(password_page)
        p_layout.setContentsMargins(0, 8, 0, 0)
        p_layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(15)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 账户选择下拉框
        self.cbo_accounts = QComboBox()
        self.cbo_accounts.setEditable(True)
        self.cbo_accounts.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cbo_accounts.setMinimumHeight(36)
        self.cbo_accounts.lineEdit().setPlaceholderText(
            tr("login.account_placeholder", "选择或输入账户")
        )
        form.addRow(tr("login.account_label", "账户"), self.cbo_accounts)

        # 密码输入框
        self.le_pass = LineEdit()
        self.le_pass.setPlaceholderText(tr("login.password_placeholder", "请输入密码"))
        self.le_pass.setEchoMode(LineEdit.EchoMode.Password)
        self.le_pass.setMinimumHeight(36)
        form.addRow(tr("login.password_label", "密码"), self.le_pass)

        p_layout.addLayout(form)

        # 保持登录
        self.cb_stay_logged_in = CheckBox(tr("login.stay_logged_in", "保持登录"))
        cb_row = QHBoxLayout()
        cb_row.addStretch()
        cb_row.addWidget(self.cb_stay_logged_in)
        cb_row.addStretch()
        p_layout.addLayout(cb_row)

        # 登录 / 取消按钮
        h = QHBoxLayout()
        h.addStretch()

        # 登录按钮
        self.btn_ok = PrimaryPushButton()
        self.btn_ok.setText(tr("login.login_btn", "登录"))
        self.btn_ok.setMinimumWidth(120)
        self.btn_ok.setMinimumHeight(36)

        # 取消按钮
        self.btn_cancel = PushButton()
        self.btn_cancel.setText(tr("login.cancel_btn", "取消"))
        self.btn_cancel.setMinimumWidth(120)
        self.btn_cancel.setMinimumHeight(36)

        h.addWidget(self.btn_ok)
        h.addWidget(self.btn_cancel)
        p_layout.addLayout(h)

        self.stacked_widget.addWidget(password_page)

        # -- 扫码登录页面 (page 1) --
        self.qr_page = QRLoginPage(parent=self)
        self.qr_page.loginSuccess.connect(self._on_qr_login_success)
        self.stacked_widget.addWidget(self.qr_page)

        # 同步两页面的"保持登录"状态
        stay_logged_in = bool(ConfigManager.get_setting("stayLoggedIn", True))
        self.cb_stay_logged_in.setChecked(stay_logged_in)
        self.qr_page.cb_stay_logged_in.setChecked(stay_logged_in)
        self.cb_stay_logged_in.stateChanged.connect(
            lambda state: self.qr_page.cb_stay_logged_in.setChecked(bool(state))
        )
        self.qr_page.cb_stay_logged_in.stateChanged.connect(
            lambda state: self.cb_stay_logged_in.setChecked(bool(state))
        )

        # 信号连接
        self.segmented_widget.currentItemChanged.connect(self._on_tab_changed)
        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_cancel.clicked.connect(self.reject)

        self.pan = None
        self.login_error = None
        # 持有后台任务引用，防止任务/信号被 GC 回收
        self._pending_tasks = []

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
            logger.debug("已加载账号 %s 的密码", account_name)
            self.le_pass.setText(account.get("passWord", ""))
        else:
            logger.debug("账号 %s 无保存信息", account_name)

    def on_ok(self):
        """登录处理（后台线程执行网络请求，避免阻塞对话框）。"""
        user = self.cbo_accounts.currentText().strip()
        pwd = self.le_pass.text()
        logger.info("登录尝试: user=%s, has_pwd=%s", user, bool(pwd))
        if not user or not pwd:
            logger.warning("登录失败: 用户名或密码为空")
            MessageBox(
                tr("login.msg_prompt", "提示"),
                tr("login.msg_enter_credentials", "请输入用户名和密码。"),
                self,
            ).exec()
            return

        # 禁用按钮防止重复提交，等待后台登录结果
        self.btn_ok.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        signals = _PasswordLoginSignals()
        task = PasswordLoginTask(user, pwd, signals)
        connect_tracked(self, signals, "finished", self.__onLoginFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onLoginFinished(self, pan, code, error):
        """后台登录完成回调（主线程）。"""
        QApplication.restoreOverrideCursor()
        self.btn_ok.setEnabled(True)

        if error or (code != 200 and code != 0):
            self.login_error = (
                error
                if error
                else tr("login.msg_login_failed_code", "登录失败，返回码: {}").format(code)
            )
            MessageBox(
                tr("login.msg_login_failed", "登录失败"),
                self.login_error,
                self,
            ).exec()
            return

        self.pan = pan
        try:
            pan.stay_logged_in = self.cb_stay_logged_in.isChecked()
            ConfigManager.set_setting(
                "stayLoggedIn", self.cb_stay_logged_in.isChecked()
            )
            if hasattr(pan, "save_file"):
                pan.save_file()
        except (IOError, OSError) as e:
            logger.warning(f"保存配置失败: {e}")
        except Exception as e:
            logger.error(f"保存配置时发生未知错误: {e}")
        logger.info("登录成功，对话框关闭: %s", user_name_of(pan))
        self.accept()

    def _on_tab_changed(self, route_key):
        """登录方式切换。"""
        if route_key == "password":
            self.stacked_widget.setCurrentIndex(0)
            self.qr_page.stop_polling()
        else:
            self.stacked_widget.setCurrentIndex(1)
            self.qr_page.start_qr_flow()

    def _on_qr_login_success(self, pan):
        """扫码登录成功回调。"""
        self.pan = pan
        try:
            pan.stay_logged_in = self.cb_stay_logged_in.isChecked()
            ConfigManager.set_setting(
                "stayLoggedIn", self.cb_stay_logged_in.isChecked()
            )
            if hasattr(pan, "save_file"):
                pan.save_file()
        except Exception as e:
            logger.warning("保存配置失败: %s", e)
        logger.info("扫码登录成功，对话框关闭: %s", pan.user_name)
        self.accept()

    def reject(self):
        """取消登录：停止扫码轮询并关闭对话框。"""
        QApplication.restoreOverrideCursor()
        self.qr_page.stop_polling()
        super().reject()

    def closeEvent(self, event):
        """关闭时停止扫码轮询。"""
        QApplication.restoreOverrideCursor()
        self.qr_page.stop_polling()
        super().closeEvent(event)

    def get_pan(self):
        """获取登录成功的Pan对象"""
        return self.pan
