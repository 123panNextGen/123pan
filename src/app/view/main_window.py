"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import QThreadPool, QTimer
from PyQt6.QtWidgets import QDialog

import sys

from qfluentwidgets import (
    NavigationItemPosition,
    FluentWindow
)
from qfluentwidgets import FluentIcon as FIF

from .file_interface import FileInterface
from .transfer_interface import TransferInterface
from .setting_interface import SettingInterface
from .cloud_interface import CloudInterface
from .trash_interface import TrashInterface
from .share_interface import ShareInterface
from .login_window import LoginDialog

from ..common.config import ConfigManager
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import AutoLoginTask
from ..tasks.signals import _AutoLoginSignals

logger = get_logger(__name__)


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("123pan")
        self.resize(900, 600)
        logger.info("MainWindow 初始化")

        # Linux 下禁用 Mica 效果，避免 "This plugin does not support setting window opacity" 错误
        if sys.platform != "win32":
            self.setMicaEffectEnabled(False)

        # 应用窗口透明度设置
        opacity = ConfigManager.get_setting("windowOpacity", 100)
        self.set_window_opacity(opacity)

        # 初始化子页面
        self.file_interface = FileInterface(self)
        self.transfer_interface = TransferInterface(self)
        self.setting_interface = SettingInterface(self)
        self.cloud_interface = CloudInterface(self)
        self.trash_interface = TrashInterface(self)
        self.share_interface = ShareInterface(self)

        # 传递传输界面引用给文件界面
        self.file_interface.transfer_interface = self.transfer_interface

        self._startup_login_flow()
        self._initNavigation()
        logger.info("MainWindow 初始化完成")

    def _initNavigation(self):
        self.addSubInterface(self.file_interface, FIF.FOLDER, tr("nav.file", "文件"))
        self.addSubInterface(self.transfer_interface, FIF.SYNC, tr("nav.transfer", "传输"))
        self.addSubInterface(self.trash_interface, FIF.DELETE, tr("nav.trash", "回收站"))
        self.addSubInterface(self.share_interface, FIF.SHARE, tr("nav.share", "分享"))
        self.addSubInterface(
            self.cloud_interface,
            FIF.CLOUD,
            tr("nav.cloud", "云盘"),
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.setting_interface,
            FIF.SETTING,
            tr("nav.settings", "设置"),
            position=NavigationItemPosition.BOTTOM,
        )

    def _startup_login_flow(self):
        """启动登录流程。

        有已保存凭证时在后台线程自动登录（Pan123 构造含网络请求），
        避免阻塞主线程导致启动白屏；无凭证时直接弹出登录框。
        """
        current_account = ConfigManager.get_current_account_name()
        current_info = (
            ConfigManager.get_account(current_account) if current_account else {}
        )
        logger.info(
            "启动登录流程: current_account=%s, has_password=%s",
            current_account or "(无)",
            bool(current_info.get("passWord")),
        )
        if current_info.get("passWord") or current_info.get("authorization"):
            # 后台自动登录（含密码/token 两种方式，行为与原先一致）
            signals = _AutoLoginSignals()
            signals.finished.connect(self.__onAutoLoginFinished)
            QThreadPool.globalInstance().start(AutoLoginTask(signals))
        else:
            logger.debug("显示登录对话框")
            self.__show_login_dialog()

    def __onAutoLoginFinished(self, pan, error):
        """后台自动登录完成回调（主线程）。"""
        if pan is not None:
            self.pan = pan
            logger.info(
                "自动登录成功: %s",
                self.pan.user_name if hasattr(self.pan, "user_name") else "?",
            )
            self.__finish_login_flow()
        else:
            logger.warning("自动登录失败: %s", error)
            self.__show_login_dialog()

    def __show_login_dialog(self):
        """显示登录对话框（主线程）。"""
        dlg = LoginDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            logger.info("用户取消登录，退出程序")
            QTimer.singleShot(0, self.close)
            return
        self.pan = dlg.get_pan()
        logger.info(
            "登录成功: %s",
            self.pan.user_name if hasattr(self.pan, "user_name") else "?",
        )
        self.__finish_login_flow()

    def __finish_login_flow(self):
        """登录成功后同步 pan 到各子界面。"""
        self.file_interface.pan = self.pan
        self._sync_pan_to_interfaces()

        self.cloud_interface.logoutRequested.connect(self.handle_logout)
        self.cloud_interface.switchAccountRequested.connect(self.handle_switch_account)

    def clear_login_config(self):
        """清除当前登录状态，但保留已保存账户"""
        ConfigManager.set_current_account("")
        logger.info("登录配置已清除")

    def set_window_opacity(self, opacity_pct):
        """设置窗口透明度。

        Args:
            opacity_pct: 透明度百分比 (30-100)，100 为完全不透明。
        """
        opacity_pct = max(30, min(100, opacity_pct))
        self.setWindowOpacity(opacity_pct / 100.0)
        logger.debug("窗口透明度设置为: %d%%", opacity_pct)

    def _sync_pan_to_interfaces(self):
        """将当前 pan 实例同步到所有子界面。"""
        self.file_interface.pan = self.pan
        self.file_interface.load_pan_and_data()
        self.transfer_interface.set_pan(self.pan)
        self.trash_interface.set_pan(self.pan)
        self.cloud_interface.set_pan(self.pan)
        self.share_interface.set_pan(self.pan)

    def handle_logout(self):
        """处理退出登录请求"""
        logger.info("用户请求退出登录")
        from qfluentwidgets import MessageBox

        msg = MessageBox(
            tr("main.logout_title", "退出登录"),
            tr("main.logout_confirm", "确定要退出登录吗？"),
            self,
        )
        if msg.exec():
            logger.debug("确认退出登录")
            self.clear_login_config()
            dlg = LoginDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.pan = dlg.get_pan()
                logger.info(
                    "新登录成功: %s",
                    self.pan.user_name if hasattr(self.pan, "user_name") else "?",
                )
                self._sync_pan_to_interfaces()
            else:
                logger.info("用户取消重新登录，退出程序")
                self.close()
        else:
            logger.debug("用户取消退出登录")

    def handle_switch_account(self):
        """处理切换账号请求"""
        logger.info("用户请求切换账号")
        dlg = LoginDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.pan = dlg.get_pan()
            logger.info(
                "切换账号成功: %s",
                self.pan.user_name if hasattr(self.pan, "user_name") else "?",
            )
            self._sync_pan_to_interfaces()
        else:
            logger.debug("用户取消切换账号")
