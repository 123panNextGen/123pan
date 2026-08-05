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
from .login_window import LoginDialog

from ..common.config import ConfigManager
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import AutoLoginTask, connect_tracked
from ..tasks.signals import _AutoLoginSignals

logger = get_logger(__name__)


class _LazyTransferProxy:
    """传输界面懒加载代理。

    文件页添加上传/下载任务时通过 __getattr__ 按需创建真实界面，
    避免在启动阶段就构建传输页（含 3 个表格，内存占用较大）。
    """

    def __init__(self, getter):
        self._getter = getter

    def __getattr__(self, name):
        return getattr(self._getter(), name)


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

        self.pan = None
        # 持有后台任务引用，防止任务/信号被 GC 回收
        self._pending_tasks = []

        # 仅创建文件页（默认页）；传输/设置/云盘/回收站/分享页懒加载，
        # 首次点击导航时才构建，显著降低启动内存峰值。
        self.file_interface = FileInterface(self)

        # 传输界面懒加载代理（文件页添加任务时按需创建，不切换页面）
        self.file_interface.transfer_interface = _LazyTransferProxy(
            lambda: self.transfer_interface
        )

        # 懒加载页面规格：route_key -> (icon, text, position)
        self._lazy_specs = {
            "TransferInterface": (
                FIF.SYNC, tr("nav.transfer", "传输"), NavigationItemPosition.TOP,
            ),
            "TrashInterface": (
                FIF.DELETE, tr("nav.trash", "回收站"), NavigationItemPosition.TOP,
            ),
            "ShareInterface": (
                FIF.SHARE, tr("nav.share", "分享"), NavigationItemPosition.TOP,
            ),
            "CloudInterface": (
                FIF.CLOUD, tr("nav.cloud", "云盘"), NavigationItemPosition.BOTTOM,
            ),
            "settingInterface": (
                FIF.SETTING, tr("nav.settings", "设置"), NavigationItemPosition.BOTTOM,
            ),
        }
        # 已懒加载创建的界面：route_key -> interface
        self._lazy_built = {}

        self._startup_login_flow()
        self._initNavigation()
        logger.info("MainWindow 初始化完成")

    def _initNavigation(self):
        self.addSubInterface(self.file_interface, FIF.FOLDER, tr("nav.file", "文件"))

        # 懒加载页面：仅注册导航项，首次点击才创建界面
        for route_key, (icon, text, position) in self._lazy_specs.items():
            self.navigationInterface.addItem(
                routeKey=route_key,
                icon=icon,
                text=text,
                onClick=lambda rk=route_key: self._open_interface(rk),
                position=position,
                tooltip=text,
            )

    @property
    def transfer_interface(self):
        """传输界面（懒加载，不切换页面）。"""
        return self._ensure_built("TransferInterface")

    def _ensure_built(self, route_key):
        """确保懒加载界面已创建并返回（不切换页面）。"""
        interface = self._lazy_built.get(route_key)
        if interface is not None:
            return interface
        interface = self._create_lazy_interface(route_key)
        self._lazy_built[route_key] = interface
        icon, text, position = self._lazy_specs[route_key]
        self.addSubInterface(interface, icon, text, position)
        return interface

    def _open_interface(self, route_key):
        """懒加载创建界面并切换到该页面（导航点击回调）。"""
        interface = self._ensure_built(route_key)
        self.switchTo(interface)

    def _create_lazy_interface(self, route_key):
        """按 route_key 构建对应的子界面（懒加载）。"""
        if route_key == "TransferInterface":
            from .transfer_interface import TransferInterface
            interface = TransferInterface(self)
            if self.pan is not None:
                interface.set_pan(self.pan)
        elif route_key == "TrashInterface":
            from .trash_interface import TrashInterface
            interface = TrashInterface(self)
            if self.pan is not None:
                interface.set_pan(self.pan)
        elif route_key == "ShareInterface":
            from .share_interface import ShareInterface
            interface = ShareInterface(self)
            if self.pan is not None:
                interface.set_pan(self.pan)
        elif route_key == "CloudInterface":
            from .cloud_interface import CloudInterface
            interface = CloudInterface(self)
            if self.pan is not None:
                interface.set_pan(self.pan)
            interface.logoutRequested.connect(self.handle_logout)
            interface.switchAccountRequested.connect(self.handle_switch_account)
        elif route_key == "settingInterface":
            from .setting_interface import SettingInterface
            interface = SettingInterface(self)
        else:
            raise KeyError(f"未知的懒加载界面: {route_key}")
        return interface

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
            task = AutoLoginTask(signals)
            connect_tracked(self, signals, "finished", self.__onAutoLoginFinished, task)
            QThreadPool.globalInstance().start(task)
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
        """将当前 pan 实例同步到已创建的子界面。

        懒加载界面在首次创建时（_create_lazy_interface）也会设置 pan。
        """
        self.file_interface.pan = self.pan
        self.file_interface.load_pan_and_data()
        for interface in self._lazy_built.values():
            if hasattr(interface, "set_pan"):
                interface.set_pan(self.pan)

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
