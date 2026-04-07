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
from .transfer_interface import TransferInterface
from .setting_interface import SettingInterface
from .cloud_interface import CloudInterface
from .login_window import LoginDialog, try_token_probe

from ..common import resource
from ..common.database import Database


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("123pan")
        self.resize(900, 600)
        self._last_file_refresh_time = 0.0

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
        if widget is self.file_interface and hasattr(self, "pan"):
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
                QTimer.singleShot(0, self.close)
                return
            self.pan = dlg.get_pan()

        # 将 pan 对象传递给 file_interface 并刷新文件列表
        self.file_interface.pan = self.pan
        self.file_interface.reload()

        # 将 pan 对象传递给 transfer_interface
        self.transfer_interface.set_pan(self.pan)

        # 将 pan 对象传递给 cloud_interface
        self.cloud_interface.set_pan(self.pan)

        # 连接退出登录信号
        self.cloud_interface.logoutRequested.connect(self.handle_logout)

    def _stop_all_transfers(self):
        """取消所有正在进行的传输任务并等待线程退出。"""
        threads_to_wait = []
        for task in self.transfer_interface.upload_tasks:
            if task.thread and task.status == "上传中":
                task.thread.cancel()
                threads_to_wait.append(task.thread)
        for task in self.transfer_interface.download_tasks:
            if task.thread and task.status in ("下载中", "校验中", "合并中"):
                task.thread.cancel()
                threads_to_wait.append(task.thread)
        for thread in threads_to_wait:
            thread.wait(5000)

    def closeEvent(self, event):
        """H6: 关闭窗口时取消/等待传输线程。"""
        self._stop_all_transfers()
        event.accept()

    def clear_login_config(self):
        """清除登录配置信息"""
        db = Database.instance()
        for key in ("userName", "passWord", "authorization", "deviceType", "osVersion", "loginuuid"):
            db.set_config(key, "")
        db.set_config("rememberPassword", False)
        db.set_config("stayLoggedIn", False)

    def handle_logout(self):
        """处理退出登录请求"""
        msg = MessageBox("退出登录", "确定要退出登录吗？", self)
        if msg.exec():
            # M8: 退出登录前停止传输
            self._stop_all_transfers()
            self.clear_login_config()
            dlg = LoginDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.pan = dlg.get_pan()
                self.file_interface.pan = self.pan
                self.file_interface.reload()
                self.transfer_interface.set_pan(self.pan)
                self.cloud_interface.set_pan(self.pan)
            else:
                self.close()
