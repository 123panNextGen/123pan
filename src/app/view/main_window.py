from PyQt6.QtCore import Qt, pyqtSignal, QEasingCurve, QUrl, QSize, QTimer
from PyQt6.QtGui import QIcon, QDesktopServices, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QFrame,
    QWidget,
    QDialog,
    QMessageBox,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
)

from qfluentwidgets import (
    NavigationAvatarWidget,
    NavigationItemPosition,
    MessageBox,
    FluentWindow,
    SplashScreen,
    SystemThemeListener,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from .file_interface import FileInterface
from .transfer_interface import TransferInterface
from .setting_interface import SettingInterface
from .cloud_interface import CloudInterface
from .login_window import LoginDialog

from ..common import resource
from ..common.api import Pan123
from ..common.config import ConfigManager


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("123pan")
        self.resize(900, 600)

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
            "云盘",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.setting_interface,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def _startup_login_flow(self):
        cfg_loaded = False
        cfg = ConfigManager.load_config()
        if ConfigManager.get_setting(
                "userName"
        ) and ConfigManager.get_setting("passWord"):
            try:
                self.pan = Pan123(readfile=True, input_pwd=False)
                res_code = self.pan.get_dir(save=False)[0]
                if res_code == 0:
                    cfg_loaded = True
                else:
                    cfg_loaded = False
            except Exception:
                cfg_loaded = False

        if not cfg_loaded:
            dlg = LoginDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                # QMessageBox.information(self, "提示", "未登录，程序将退出。")
                QTimer.singleShot(0, self.close)
                return
            self.pan = dlg.get_pan()

        # 将 pan 对象传递给 file_interface 并刷新文件列表
        self.file_interface.pan = self.pan
        self.file_interface._FileInterface__loadPanAndData()

        # 将 pan 对象传递给 transfer_interface
        self.transfer_interface.set_pan(self.pan)

        # 将 pan 对象传递给 cloud_interface
        self.cloud_interface.set_pan(self.pan)

        # 连接退出登录信号
        self.cloud_interface.logoutRequested.connect(self.handle_logout)

    def clear_login_config(self):
        """清除登录配置信息"""
        config = ConfigManager.load_config()
        # 清除登录相关的信息
        config["userName"] = ""
        config["passWord"] = ""
        config["authorization"] = ""
        config["deviceType"] = ""
        config["osVersion"] = ""
        config["loginuuid"] = ""
        ConfigManager.save_config(config)

    def handle_logout(self):
        """处理退出登录请求"""
        # 确认对话框
        from qfluentwidgets import MessageBox
        msg = MessageBox("退出登录", "确定要退出登录吗？", self)
        if msg.exec():
            # 清除登录配置
            self.clear_login_config()
            # 显示登录对话框
            dlg = LoginDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                # 登录成功，更新 pan 对象
                self.pan = dlg.get_pan()
                self.file_interface.pan = self.pan
                self.file_interface._FileInterface__loadPanAndData()
                self.transfer_interface.set_pan(self.pan)
                self.cloud_interface.set_pan(self.pan)
            else:
                # 用户取消登录，关闭程序
                self.close()
