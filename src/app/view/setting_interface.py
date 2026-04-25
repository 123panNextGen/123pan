from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFileDialog
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from qfluentwidgets import (
    ExpandLayout,
    SettingCardGroup,
    PushSettingCard,
    SwitchSettingCard,
    ScrollArea,
    PrimaryPushSettingCard,
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import isWin11, ConfigManager
from ..common.const import YEAR, ABOUT_URL, VERSION
from ..common.style_sheet import StyleSheet


class SettingInterface(ScrollArea):
    """设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        self.settingLabel = QLabel(self.tr("设置"), self)

        self.musicInThisPCGroup = SettingCardGroup(
            self.tr("下载设置"), self.scrollWidget
        )
        self.downloadFolderCard = PushSettingCard(
            self.tr("选择文件夹"),
            FIF.DOWNLOAD,
            self.tr("下载目录"),
            ConfigManager.get_setting("defaultDownloadPath", str(Path.home() / "Downloads")),
            self.musicInThisPCGroup,
        )

        # 添加询问下载位置开关
        self.askDownloadLocationCard = SwitchSettingCard(
            FIF.DOWNLOAD,
            self.tr("每次询问下载位置"),
            self.tr("下载文件时是否每次都询问保存位置"),
            parent=self.musicInThisPCGroup,
        )
        # 手动设置开关状态
        self.askDownloadLocationCard.setChecked(
            ConfigManager.get_setting("askDownloadLocation", True)
        )

        self.personalGroup = SettingCardGroup(self.tr("个性化"), self.scrollWidget)
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            self.tr("Mica 效果"),
            self.tr("在窗口和表面上应用半透明效果"),
            isWin11(),
            self.personalGroup,
        )

        self.aboutGroup = SettingCardGroup(self.tr("关于"), self.scrollWidget)
        self.aboutCard = PrimaryPushSettingCard(
            self.tr("项目页面"),
            FIF.INFO,
            self.tr("关于"),
            "123pan" + f"{VERSION}" + " © Copyright" + f" {YEAR}",
            self.aboutGroup,
        )

        self.__initWidget()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 80, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("settingInterface")

        # initialize style sheet
        self.scrollWidget.setObjectName("scrollWidget")
        self.settingLabel.setObjectName("settingLabel")
        StyleSheet.SETTING_INTERFACE.apply(self)

        self.micaCard.setEnabled(isWin11())

        self.__initLayout()
        self.__connectSignalToSlot()

    def __initLayout(self):
        self.settingLabel.move(36, 30)

        # add cards to group
        self.musicInThisPCGroup.addSettingCard(self.downloadFolderCard)
        self.musicInThisPCGroup.addSettingCard(self.askDownloadLocationCard)

        self.personalGroup.addSettingCard(self.micaCard)

        self.aboutGroup.addSettingCard(self.aboutCard)

        # add setting card group to layout
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.musicInThisPCGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    def __onDownloadFolderCardClicked(self):
        """download folder card clicked slot"""
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose folder"), "./")
        if not folder or ConfigManager.get_setting("defaultDownloadPath") == folder:
            return

        self.downloadFolderCard.setContent(folder)

        # 同时更新默认下载位置
        config = ConfigManager.load_config()
        config["settings"]["defaultDownloadPath"] = folder
        ConfigManager.save_config(config)

    def __onAskDownloadLocationChanged(self, checked):
        """ask download location changed slot"""
        # 加载当前配置
        config = ConfigManager.load_config()
        # 更新askDownloadLocation的值
        config["settings"]["askDownloadLocation"] = checked
        # 保存配置
        ConfigManager.save_config(config)

    def __connectSignalToSlot(self):
        """connect signal to slot"""
        # cfg.appRestartSig.connect(self.__showRestartTooltip)

        # music in the pc
        self.downloadFolderCard.clicked.connect(self.__onDownloadFolderCardClicked)
        self.askDownloadLocationCard.checkedChanged.connect(
            self.__onAskDownloadLocationChanged
        )

        # personalization
        # cfg.themeChanged.connect(setTheme)
        # self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c))
        # self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged)

        # about
        self.aboutCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ABOUT_URL))
        )
