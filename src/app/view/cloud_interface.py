"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from qfluentwidgets import (
    FluentIcon as FIF,
    SettingCardGroup,
    PushSettingCard,
    SettingCard,
    ScrollArea,
)

from ..common.log import get_logger
from ..common.i18n import tr
from ..common.style_sheet import StyleSheet
from ..tasks.file_tasks import LoadDeviceListTask, LoadUserInfoTask
from ..tasks.signals import _DeviceListSignals, _UserInfoSignals

logger = get_logger(__name__)


def _mask_username(username):
    """如果用户名类似手机号，隐藏中间4位"""
    if not username:
        return ""

    # 检查是否为11位数字（手机号格式）
    if len(username) == 11 and username.isdigit():
        return f"{username[:3]}****{username[7:]}"

    return username


class CloudInterface(ScrollArea):
    """云盘页面"""

    # 定义退出登录信号
    logoutRequested = pyqtSignal()
    switchAccountRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.pan = None
        self._user_info = None
        self.setObjectName("CloudInterface")

        # 滚动区域内部容器
        self.scrollWidget = QWidget()
        self.scrollWidget.setObjectName("scrollWidget")

        self.mainLayout = QVBoxLayout(self.scrollWidget)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        # 添加标题
        title_label = QLabel(tr("cloud.title", "云盘信息"))
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        self.mainLayout.addWidget(title_label)

        # ---- 账户信息卡片组 ----
        self.accountGroup = SettingCardGroup(tr("cloud.account_info", "账户信息"), self.scrollWidget)

        # 用户名
        self.username_card = SettingCard(
            FIF.PEOPLE,
            tr("cloud.account", "账户"),
            tr("cloud.account_desc", "当前登录的账户信息"),
            self.accountGroup,
        )
        self.username_label = QLabel()
        font = QFont()
        font.setPointSize(12)
        self.username_label.setFont(font)
        self.username_card.hBoxLayout.addWidget(
            self.username_label, 0, Qt.AlignmentFlag.AlignRight
        )
        self.username_card.hBoxLayout.addSpacing(16)
        self.accountGroup.addSettingCard(self.username_card)

        # UID
        self.uid_card = SettingCard(
            FIF.PEOPLE,
            tr("cloud.uid", "UID"),
            tr("cloud.uid_desc", "用户唯一标识"),
            self.accountGroup,
        )
        self.uid_label = QLabel()
        self.uid_card.hBoxLayout.addWidget(
            self.uid_label, 0, Qt.AlignmentFlag.AlignRight
        )
        self.uid_card.hBoxLayout.addSpacing(16)
        self.accountGroup.addSettingCard(self.uid_card)

        # VIP 状态
        self.vip_card = SettingCard(
            FIF.CERTIFICATE,
            tr("cloud.vip", "VIP"),
            tr("cloud.vip_desc", "会员状态"),
            self.accountGroup,
        )
        self.vip_label = QLabel()
        self.vip_card.hBoxLayout.addWidget(
            self.vip_label, 0, Qt.AlignmentFlag.AlignRight
        )
        self.vip_card.hBoxLayout.addSpacing(16)
        self.accountGroup.addSettingCard(self.vip_card)

        # 切换账号
        self.switch_card = PushSettingCard(
            tr("cloud.switch_account", "切换账号"),
            FIF.SYNC,
            tr("cloud.switch_account_title", "切换登录账号"),
            tr("cloud.switch_account_desc", "从已保存账号或新账号登录"),
            self.accountGroup,
        )
        self.switch_card.clicked.connect(self.switchAccountRequested.emit)
        self.accountGroup.addSettingCard(self.switch_card)

        # 登录设备
        self.deviceGroup = SettingCardGroup(
            tr("cloud.device_title", "登录设备"), self.scrollWidget
        )
        self._device_cards = []  # 动态创建的设备卡片列表

        # 退出登录
        self.logout_card = PushSettingCard(
            tr("cloud.logout", "退出登录"),
            FIF.CLOSE,
            tr("cloud.logout_title", "退出登录"),
            tr("cloud.logout_desc", "退出当前登录的账户"),
            self.accountGroup,
        )
        self.logout_card.clicked.connect(self.logoutRequested.emit)
        self.accountGroup.addSettingCard(self.logout_card)

        self.mainLayout.addWidget(self.accountGroup)

        # ---- 存储信息卡片组 ----
        self.storageGroup = SettingCardGroup(tr("cloud.storage_info", "存储信息"), self.scrollWidget)

        # 空间用量
        self.space_card = SettingCard(
            FIF.FOLDER,
            tr("cloud.space", "空间用量"),
            tr("cloud.space_desc", "已用空间 / 总空间"),
            self.storageGroup,
        )
        self.space_label = QLabel()
        self.space_card.hBoxLayout.addWidget(
            self.space_label, 0, Qt.AlignmentFlag.AlignRight
        )
        self.space_card.hBoxLayout.addSpacing(16)
        self.storageGroup.addSettingCard(self.space_card)

        # 文件数量
        self.file_count_card = SettingCard(
            FIF.DOCUMENT,
            tr("cloud.file_count", "文件数量"),
            tr("cloud.file_count_desc", "当前云盘中的文件总数"),
            self.storageGroup,
        )
        self.file_count_label = QLabel()
        self.file_count_card.hBoxLayout.addWidget(
            self.file_count_label, 0, Qt.AlignmentFlag.AlignRight
        )
        self.file_count_card.hBoxLayout.addSpacing(16)
        self.storageGroup.addSettingCard(self.file_count_card)

        # 直链流量
        self.traffic_card = SettingCard(
            FIF.LINK,
            tr("cloud.traffic", "直链流量"),
            tr("cloud.traffic_desc", "下载文件使用的直链流量配额"),
            self.storageGroup,
        )
        self.traffic_label = QLabel()
        self.traffic_card.hBoxLayout.addWidget(
            self.traffic_label, 0, Qt.AlignmentFlag.AlignRight
        )
        self.traffic_card.hBoxLayout.addSpacing(16)
        self.storageGroup.addSettingCard(self.traffic_card)

        self.mainLayout.addWidget(self.storageGroup)
        self.mainLayout.addWidget(self.deviceGroup)
        self.mainLayout.addStretch()

        # 配置滚动区域
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)

        StyleSheet.VIEW_INTERFACE.apply(self)

    def set_pan(self, pan):
        """设置Pan123实例并更新用户信息"""
        self.pan = pan
        if not self.pan:
            return

        # 显示用户名
        if hasattr(self.pan, "user_name"):
            username = _mask_username(self.pan.user_name)
            self.username_label.setText(username)

        # 异步获取用户云盘信息与设备列表（后台线程，不阻塞 GUI）
        user_signals = _UserInfoSignals()
        user_signals.finished.connect(self.__onUserInfoLoaded)
        QThreadPool.globalInstance().start(
            LoadUserInfoTask(self.pan, user_signals)
        )

        device_signals = _DeviceListSignals()
        device_signals.finished.connect(self.__onDeviceListLoaded)
        QThreadPool.globalInstance().start(
            LoadDeviceListTask(self.pan, device_signals)
        )

    def __onUserInfoLoaded(self, user_info, error):
        """用户信息加载完成回调（主线程）。"""
        if error or user_info is None:
            logger.warning("获取用户信息失败: %s", error)
            self._show_user_info_error()
            return
        self._user_info = user_info
        self._update_display()

    def _update_display(self):
        """更新界面上的用户信息展示。"""
        if not self._user_info:
            return

        info = self._user_info

        # UID
        self.uid_label.setText(str(info.uid))

        # VIP 状态
        if info.vip:
            self.vip_label.setText(f"VIP{info.vip_level} · {info.vip_expire} 到期")
            self.vip_label.setStyleSheet("color: #e6a23c; font-weight: bold;")
        else:
            self.vip_label.setText("非会员")

        # 空间用量（含百分比）
        used_str = info.space_used_str()
        total_str = info.space_total_str()
        if info.space_total > 0:
            pct = info.space_used / info.space_total * 100
            self.space_label.setText(f"{used_str} / {total_str} ({pct:.1f}%)")
        else:
            self.space_label.setText(f"{used_str} / {total_str}")

        # 文件数量
        self.file_count_label.setText(str(info.file_count))

        # 直链流量
        self.traffic_label.setText(info.traffic_str())

        logger.info(
            "用户信息已更新: uid=%s, vip=%s, space=%s/%s",
            info.uid, info.vip, used_str, total_str,
        )

    def _show_user_info_error(self):
        """用户信息获取失败时显示占位文本。"""
        self.uid_label.setText("-")
        self.vip_label.setText("-")
        self.space_label.setText("-")
        self.file_count_label.setText("-")
        self.traffic_label.setText("-")

    def __onDeviceListLoaded(self, device_data, error):
        """设备列表加载完成回调（主线程）。"""
        if error or device_data is None:
            logger.warning("获取设备列表失败: %s", error)
            return
        self._update_device_display(device_data)

    def _update_device_display(self, device_data):
        """更新设备列表界面。"""
        # 清除旧卡片
        for card in self._device_cards:
            self.deviceGroup.removeSettingCard(card)
            card.deleteLater()
        self._device_cards.clear()

        devices = device_data.device_list
        master = device_data.master_device

        if not devices:
            return

        for dev in devices:
            cur = tr("cloud.device_current", "当前") if dev.cur_device else ""
            title = tr("cloud.device_item", "{}. {} ({}) {}").format(
                devices.index(dev) + 1, dev.device_name, dev.device_type, cur
            )
            content = tr("cloud.device_detail", "平台: {} | IP: {} | 登录: {} | 方式: {}").format(
                dev.plat_form, dev.ip, dev.last_login_time, dev.login_type
            )
            card = SettingCard(FIF.IOT, title, content, self.deviceGroup)
            self.deviceGroup.addSettingCard(card)
            self._device_cards.append(card)

        if master:
            title = tr("cloud.device_master_item", "{} ({}) — 主设备").format(
                master.device_name, master.device_type
            )
            content = tr("cloud.device_master_detail", "平台: {} | IP: {} | 登录: {}").format(
                master.plat_form, master.ip, master.last_login_time
            )
            card = SettingCard(FIF.HOME, title, content, self.deviceGroup)
            self.deviceGroup.addSettingCard(card)
            self._device_cards.append(card)

        logger.info("设备列表已更新: %d 个设备", len(devices))
