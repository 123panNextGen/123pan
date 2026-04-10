import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from qfluentwidgets import (
    NavigationItemPosition,
    MessageBox,
    FluentWindow,
)
from qfluentwidgets import FluentIcon as FIF

from .file_interface import FileInterface
from .transfer_interface import (
    DOWNLOAD_ACTIVE_STATUSES,
    UPLOAD_ACTIVE_STATUSES,
    TransferInterface,
)
from .setting_interface import SettingInterface
from .cloud_interface import CloudInterface
from .login_window import LoginDialog, try_token_probe

from ..common import resource  # noqa: F401 -- 触发 qInitResources()
from ..common.database import Database


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("123pan-open")
        self.resize(900, 600)

        # 导航栏始终展开，不允许收起
        nav = self.navigationInterface
        nav.setExpandWidth(120)
        nav.setMinimumExpandWidth(0)
        nav.setCollapsible(False)
        nav.setMenuButtonVisible(False)
        self._last_file_refresh_time = 0.0
        self.login_success = False

        # 初始化子页面
        self.file_interface = FileInterface(self)
        self.transfer_interface = TransferInterface(self)
        self.setting_interface = SettingInterface(self)
        self.cloud_interface = CloudInterface(self)

        # 传递传输界面引用给文件界面
        self.file_interface.transfer_interface = self.transfer_interface

        self._startup_login_flow()
        self._initNavigation()

    def _initNavigation(self):
        self.addSubInterface(self.file_interface, FIF.FOLDER, "文件")
        self.addSubInterface(self.transfer_interface, FIF.SYNC, "传输")
        self.addSubInterface(
            self.cloud_interface,
            FIF.CLOUD,
            "账户",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.setting_interface,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

        self.stackedWidget.currentChanged.connect(self._onPageChanged)

    def _onPageChanged(self, index):
        widget = self.stackedWidget.widget(index)
        if widget is self.file_interface and self.pan is not None:
            now = time.time()
            if now - self._last_file_refresh_time > 30:
                self.file_interface.refresh()
                self._last_file_refresh_time = now

    def _startup_login_flow(self):
        db = Database.instance()
        self.pan = None

        # 尝试 token 探测
        stay_logged_in = bool(db.get_config("stayLoggedIn", True))
        if stay_logged_in:
            self.pan = try_token_probe(db)

        # token 无效或未开启保持登录，弹出登录对话框
        if self.pan is None:
            dlg = LoginDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                dlg.deleteLater()
                return
            self.pan = dlg.get_pan()
            dlg.deleteLater()

        self.login_success = True

        # 先设置各子页面的 pan（含 account_name），再 reload
        # 避免 reload 中异步任务的 context 捕获到空 account_name
        self.transfer_interface.set_pan(self.pan)
        self.cloud_interface.set_pan(self.pan)

        self.file_interface.pan = self.pan
        self.file_interface.reload()

        # H1: 注册 token 过期回调
        self.pan.on_token_expired = self._handle_token_expired

        # 连接退出登录信号
        self.cloud_interface.logoutRequested.connect(self.handle_logout)

    def _handle_token_expired(self):
        """H1: token 过期时在主线程弹出登录对话框。"""
        QTimer.singleShot(0, self._show_relogin_dialog)

    def _show_relogin_dialog(self):
        msg = MessageBox("登录过期", "登录凭证已过期，请重新登录。", self)
        msg.exec()
        dlg = LoginDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.pan = dlg.get_pan()
            self.pan.on_token_expired = self._handle_token_expired
            self.transfer_interface.set_pan(self.pan, force=True)
            self.cloud_interface.set_pan(self.pan)
            self.file_interface.pan = self.pan
            self.file_interface.reload()
        else:
            self.close()

    def _stop_all_transfers(self):
        """取消所有正在进行的传输任务并等待线程退出。"""
        threads_to_wait = []
        seen = set()
        for thread in list(self.transfer_interface.upload_threads):
            if thread is None or id(thread) in seen:
                continue
            thread.cancel()
            threads_to_wait.append(thread)
            seen.add(id(thread))
        for thread in list(self.transfer_interface.download_threads):
            if thread is None or id(thread) in seen:
                continue
            thread.cancel()
            threads_to_wait.append(thread)
            seen.add(id(thread))
        for task in self.transfer_interface.upload_tasks:
            if task.thread and id(task.thread) not in seen and task.status in UPLOAD_ACTIVE_STATUSES:
                task.thread.cancel()
                threads_to_wait.append(task.thread)
                seen.add(id(task.thread))
        for task in self.transfer_interface.download_tasks:
            if task.thread and id(task.thread) not in seen and task.status in DOWNLOAD_ACTIVE_STATUSES:
                task.thread.cancel()
                threads_to_wait.append(task.thread)
                seen.add(id(task.thread))
        # M11: 总超时模式，避免串行等待阻塞 UI
        deadline = time.monotonic() + 10
        for thread in threads_to_wait:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0:
                break
            thread.wait(remaining_ms)

    def closeEvent(self, event):
        """H6: 关闭窗口时取消/等待传输线程。"""
        self._stop_all_transfers()
        event.accept()
        QApplication.instance().quit()

    def clear_login_config(self):
        """清除登录配置信息"""
        db = Database.instance()
        for key in ("userName", "passWord", "authorization", "deviceType", "osVersion", "loginuuid"):
            db.set_config(key, "")
        db.set_config("rememberPassword", False)

    def handle_logout(self):
        """处理退出登录请求"""
        msg = MessageBox("退出登录", "确定要退出登录吗？", self)
        if msg.exec():
            # M8: 退出登录前停止传输
            self._stop_all_transfers()
            self._force_cleanup_tasks()
            self.clear_login_config()
            dlg = LoginDialog(self)
            dlg.deleteLater()
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.pan = dlg.get_pan()
                self.pan.on_token_expired = self._handle_token_expired
                self.transfer_interface.set_pan(self.pan, force=True)
                self.cloud_interface.set_pan(self.pan)
                self.file_interface.pan = self.pan
                self.file_interface.reload()
            else:
                self.close()

    def _force_cleanup_tasks(self):
        """M7: 强制清理所有残留任务状态，防止重登后线程冲突。"""
        for task in self.transfer_interface.upload_tasks:
            if task.thread is not None:
                try:
                    task.thread.disconnect()
                except TypeError:
                    pass
                task.thread = None
            task.status = "已取消"
        for task in self.transfer_interface.download_tasks:
            if task.thread is not None:
                try:
                    task.thread.disconnect()
                except TypeError:
                    pass
                task.thread = None
            task.status = "已取消"
        self.transfer_interface.upload_threads.clear()
        self.transfer_interface.download_threads.clear()
