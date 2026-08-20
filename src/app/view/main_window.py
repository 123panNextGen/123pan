"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QDialog, QMenu, QSystemTrayIcon

import sys

from qfluentwidgets import (
    NavigationItemPosition,
    FluentWindow
)
from .file_interface import FileInterface
from .login_window import LoginDialog

from ..common.config import ConfigManager
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import AutoLoginTask, connect_tracked
from ..tasks.signals import _AutoLoginSignals
from ..tasks.sync_manager import SyncManager

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
        self.setMinimumSize(760, 520)
        logger.info("MainWindow 初始化")

        # Linux 下禁用 Mica 效果，避免 "This plugin does not support setting window opacity" 错误
        if sys.platform != "win32":
            self.setMicaEffectEnabled(False)

        # Linux 平台的 Qt 窗口插件可能不支持窗口透明度，避免触发插件警告。
        opacity = ConfigManager.get_setting("windowOpacity", 100)
        if sys.platform != "linux" and opacity < 100:
            self.set_window_opacity(opacity)

        self.pan = None
        # 持有后台任务引用，防止任务/信号被 GC 回收
        self._pending_tasks = []

        # 全局同步调度器：独立于界面存在，托盘/后台运行期间仍按频率同步
        self._sync_manager = SyncManager(self)
        # 是否已登录（控制关闭窗口时是否最小化到托盘）
        self._logged_in = False
        # 强制退出标记（托盘菜单「退出」绕过最小化到托盘）
        self._force_quit = False
        # 系统托盘
        self._tray = None
        # 启动最小化到托盘的检查标记（仅首次登录时生效）
        self._tray_checked_start_min = False

        # 仅创建文件页（默认页）；传输/设置/云盘/回收站/分享/同步页懒加载，
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
            "SyncInterface": (
                FIF.UPDATE, tr("nav.sync", "同步"), NavigationItemPosition.TOP,
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
        # NavigationWidget.clicked 是 Signal(bool)，onClick 会被传入 True，
        # 因此 lambda 需接收该参数（checked），避免覆盖 rk=route_key 默认值。
        for route_key, (icon, text, position) in self._lazy_specs.items():
            self.navigationInterface.addItem(
                routeKey=route_key,
                icon=icon,
                text=text,
                onClick=lambda checked=False, rk=route_key: self._open_interface(rk),
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
        elif route_key == "SyncInterface":
            from .sync_interface import SyncInterface
            interface = SyncInterface(self._sync_manager, pan=self.pan, parent=self)
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
        self._logged_in = True
        self._sync_manager.set_pan(self.pan)
        self.file_interface.pan = self.pan
        self._sync_pan_to_interfaces()
        self.__ensure_tray()
        # 启动时最小化到托盘（后台同步）
        if not self._tray_checked_start_min:
            self._tray_checked_start_min = True
            if ConfigManager.get_setting("startMinimized", False):
                self.hide_to_tray()

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
        if sys.platform == "linux":
            return
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
            self._logged_in = False
            self._sync_manager.clear_pan()
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
                self._force_quit = True
                self.close()
        else:
            logger.debug("用户取消退出登录")

    def handle_switch_account(self):
        """处理切换账号请求"""
        logger.info("用户请求切换账号")
        dlg = LoginDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._sync_manager.clear_pan()
            self.pan = dlg.get_pan()
            logger.info(
                "切换账号成功: %s",
                self.pan.user_name if hasattr(self.pan, "user_name") else "?",
            )
            self._sync_manager.set_pan(self.pan)
            self._sync_pan_to_interfaces()
        else:
            logger.debug("用户取消切换账号")

    # ---- 系统托盘 ----

    @property
    def sync_manager(self):
        """全局同步调度器（设置页/托盘使用）。"""
        return self._sync_manager

    def __ensure_tray(self):
        """创建系统托盘（登录后创建，未登录时不拦截关闭）。"""
        if self._tray is not None:
            return

        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(FIF.CLOUD.icon())
        self._tray.setToolTip("123pan")

        menu = QMenu()
        show_action = menu.addAction(
            FIF.PLAY.icon(), tr("tray.show", "显示主窗口")
        )
        sync_action = menu.addAction(
            FIF.SYNC.icon(), tr("tray.sync_now", "立即同步全部")
        )
        open_sync_action = menu.addAction(
            FIF.UPDATE.icon(), tr("tray.open_sync", "打开同步页面")
        )
        menu.addSeparator()
        quit_action = menu.addAction(
            FIF.CLOSE.icon(), tr("tray.quit", "退出")
        )

        show_action.triggered.connect(self.show_from_tray)
        sync_action.triggered.connect(
            lambda: self._sync_manager.run_all_enabled()
        )
        open_sync_action.triggered.connect(
            lambda: self._open_interface("SyncInterface")
        )
        quit_action.triggered.connect(self.quit_from_tray)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        logger.info("系统托盘已启用")

    def _on_tray_activated(self, reason):
        """单击/双击托盘图标恢复主窗口。"""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_from_tray()

    def show_from_tray(self):
        """从托盘恢复主窗口。"""
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        """最小化到系统托盘（后台继续同步）。"""
        if self._tray is None:
            self.__ensure_tray()
        self.hide()
        if self._tray is not None:
            self._tray.showMessage(
                "123pan",
                tr("tray.minimized_msg", "已最小化到系统托盘，同步任务将继续在后台运行"),
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def quit_from_tray(self):
        """托盘菜单退出：绕过最小化到托盘直接退出。"""
        self._force_quit = True
        self.close()

    def closeEvent(self, event):
        """关闭窗口：开启「关闭时最小化到托盘」且已登录时隐藏而非退出。"""
        if (
            not self._force_quit
            and self._logged_in
            and self._tray is not None
            and ConfigManager.get_setting("closeToTray", False)
        ):
            self.hide_to_tray()
            event.ignore()
            return
        # 正常退出：停止传输线程、同步调度、隐藏托盘
        transfer = self._lazy_built.get("TransferInterface")
        if transfer is not None:
            transfer.shutdown()
        self._sync_manager.shutdown()
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
