from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFileDialog
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from qfluentwidgets import (
    ExpandLayout,
    SettingCardGroup,
    PushSettingCard,
    SwitchSettingCard,
    ScrollArea,
    PrimaryPushSettingCard,
    SettingCard,
    SpinBox,
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import isWin11
from ..common.database import Database
from ..common.const import YEAR, ABOUT_URL, VERSION, BUILD_TIME
from ..common.style_sheet import StyleSheet


class SettingInterface(ScrollArea):
    """设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        self.settingLabel = QLabel(self.tr("设置"), self)

        self.musicInThisPCGroup = SettingCardGroup(
            self.tr("传输设置"), self.scrollWidget
        )
        self.downloadFolderCard = PushSettingCard(
            self.tr("选择文件夹"),
            FIF.DOWNLOAD,
            self.tr("下载目录"),
            Database.instance().get_config("defaultDownloadPath", str(Path.home() / "Downloads")),
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
            Database.instance().get_config("askDownloadLocation", True)
        )

        # 下载线程数
        self.downloadThreadsCard = SettingCard(
            FIF.DOWNLOAD,
            self.tr("下载线程数"),
            self.tr("并发下载的最大线程数（1-16）"),
            self.musicInThisPCGroup,
        )
        self.downloadThreadsSpinBox = SpinBox(self.downloadThreadsCard)
        self.downloadThreadsSpinBox.setRange(1, 16)
        self.downloadThreadsSpinBox.setValue(
            int(Database.instance().get_config("maxDownloadThreads", 3))
        )
        self.downloadThreadsSpinBox.setFixedWidth(120)
        self.downloadThreadsCard.hBoxLayout.addWidget(self.downloadThreadsSpinBox)
        self.downloadThreadsCard.hBoxLayout.addSpacing(16)

        # 上传线程数
        self.uploadThreadsCard = SettingCard(
            FIF.UP,
            self.tr("上传线程数"),
            self.tr("并发上传的最大线程数（1-16）"),
            self.musicInThisPCGroup,
        )
        self.uploadThreadsSpinBox = SpinBox(self.uploadThreadsCard)
        self.uploadThreadsSpinBox.setRange(1, 16)
        self.uploadThreadsSpinBox.setValue(
            int(Database.instance().get_config("maxUploadThreads", 16))
        )
        self.uploadThreadsSpinBox.setFixedWidth(120)
        self.uploadThreadsCard.hBoxLayout.addWidget(self.uploadThreadsSpinBox)
        self.uploadThreadsCard.hBoxLayout.addSpacing(16)

        # 同时下载任务数
        self.concurrentDownloadsCard = SettingCard(
            FIF.DOWNLOAD,
            self.tr("同时下载任务数"),
            self.tr("允许同时进行的下载任务数（1-5）"),
            self.musicInThisPCGroup,
        )
        self.concurrentDownloadsSpinBox = SpinBox(self.concurrentDownloadsCard)
        self.concurrentDownloadsSpinBox.setRange(1, 5)
        self.concurrentDownloadsSpinBox.setValue(
            int(Database.instance().get_config("maxConcurrentDownloads", 3))
        )
        self.concurrentDownloadsSpinBox.setFixedWidth(120)
        self.concurrentDownloadsCard.hBoxLayout.addWidget(self.concurrentDownloadsSpinBox)
        self.concurrentDownloadsCard.hBoxLayout.addSpacing(16)

        # 同时上传任务数
        self.concurrentUploadsCard = SettingCard(
            FIF.UP,
            self.tr("同时上传任务数"),
            self.tr("允许同时进行的上传任务数（1-5）"),
            self.musicInThisPCGroup,
        )
        self.concurrentUploadsSpinBox = SpinBox(self.concurrentUploadsCard)
        self.concurrentUploadsSpinBox.setRange(1, 5)
        self.concurrentUploadsSpinBox.setValue(
            int(Database.instance().get_config("maxConcurrentUploads", 3))
        )
        self.concurrentUploadsSpinBox.setFixedWidth(120)
        self.concurrentUploadsCard.hBoxLayout.addWidget(self.concurrentUploadsSpinBox)
        self.concurrentUploadsCard.hBoxLayout.addSpacing(16)

        # 重试次数
        self.retryAttemptsCard = SettingCard(
            FIF.SYNC,
            self.tr("最大重试次数"),
            self.tr("网络请求失败后的最大重试次数（1-10）"),
            self.musicInThisPCGroup,
        )
        self.retryAttemptsSpinBox = SpinBox(self.retryAttemptsCard)
        self.retryAttemptsSpinBox.setRange(1, 10)
        self.retryAttemptsSpinBox.setValue(
            int(Database.instance().get_config("retryMaxAttempts", 3))
        )
        self.retryAttemptsSpinBox.setFixedWidth(120)
        self.retryAttemptsCard.hBoxLayout.addWidget(self.retryAttemptsSpinBox)
        self.retryAttemptsCard.hBoxLayout.addSpacing(16)

        # 下载分片大小
        self.downloadPartSizeCard = SettingCard(
            FIF.DOWNLOAD,
            self.tr("下载分片大小"),
            self.tr("单个分片大小（4-32 MB，整数）"),
            self.musicInThisPCGroup,
        )
        self.downloadPartSizeSpinBox = SpinBox(self.downloadPartSizeCard)
        self.downloadPartSizeSpinBox.setRange(4, 32)
        self.downloadPartSizeSpinBox.setSuffix(" MB")
        self.downloadPartSizeSpinBox.setValue(
            int(Database.instance().get_config("downloadPartSizeMB", 5))
        )
        self.downloadPartSizeSpinBox.setFixedWidth(120)
        self.downloadPartSizeCard.hBoxLayout.addWidget(self.downloadPartSizeSpinBox)
        self.downloadPartSizeCard.hBoxLayout.addSpacing(16)

        # 上传分片大小
        self.uploadPartSizeCard = SettingCard(
            FIF.UP,
            self.tr("上传分片大小"),
            self.tr("单个分片大小（5-16 MB，整数）"),
            self.musicInThisPCGroup,
        )
        self.uploadPartSizeSpinBox = SpinBox(self.uploadPartSizeCard)
        self.uploadPartSizeSpinBox.setRange(5, 16)
        self.uploadPartSizeSpinBox.setSuffix(" MB")
        self.uploadPartSizeSpinBox.setValue(
            int(Database.instance().get_config("uploadPartSizeMB", 5))
        )
        self.uploadPartSizeSpinBox.setFixedWidth(120)
        self.uploadPartSizeCard.hBoxLayout.addWidget(self.uploadPartSizeSpinBox)
        self.uploadPartSizeCard.hBoxLayout.addSpacing(16)

        self.personalGroup = SettingCardGroup(self.tr("个性化"), self.scrollWidget)
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            self.tr("Mica 效果"),
            self.tr("在窗口和表面上应用半透明效果"),
            isWin11(),
            self.personalGroup,
        )

        self.aboutGroup = SettingCardGroup(self.tr("关于"), self.scrollWidget)
        about_text = f"123pan-open {VERSION} © Copyright {YEAR}"
        if BUILD_TIME:
            about_text += f"  |  构建于 {BUILD_TIME}"
        self.aboutCard = PrimaryPushSettingCard(
            self.tr("项目页面"),
            FIF.INFO,
            self.tr("关于"),
            about_text,
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
        self.musicInThisPCGroup.addSettingCard(self.downloadThreadsCard)
        self.musicInThisPCGroup.addSettingCard(self.uploadThreadsCard)
        self.musicInThisPCGroup.addSettingCard(self.concurrentDownloadsCard)
        self.musicInThisPCGroup.addSettingCard(self.concurrentUploadsCard)
        self.musicInThisPCGroup.addSettingCard(self.retryAttemptsCard)
        self.musicInThisPCGroup.addSettingCard(self.downloadPartSizeCard)
        self.musicInThisPCGroup.addSettingCard(self.uploadPartSizeCard)

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
        if not folder or Database.instance().get_config("defaultDownloadPath") == folder:
            return
        self.downloadFolderCard.setContent(folder)
        Database.instance().set_config("defaultDownloadPath", folder)

    def __onAskDownloadLocationChanged(self, checked):
        """ask download location changed slot"""
        Database.instance().set_config("askDownloadLocation", checked)

    def __onDownloadThreadsChanged(self, value):
        Database.instance().set_config("maxDownloadThreads", value)

    def __onUploadThreadsChanged(self, value):
        Database.instance().set_config("maxUploadThreads", value)

    def __onConcurrentDownloadsChanged(self, value):
        Database.instance().set_config("maxConcurrentDownloads", value)

    def __onConcurrentUploadsChanged(self, value):
        Database.instance().set_config("maxConcurrentUploads", value)

    def __onRetryAttemptsChanged(self, value):
        Database.instance().set_config("retryMaxAttempts", value)

    def __onDownloadPartSizeChanged(self, value):
        Database.instance().set_config("downloadPartSizeMB", value)

    def __onUploadPartSizeChanged(self, value):
        Database.instance().set_config("uploadPartSizeMB", value)

    def __connectSignalToSlot(self):
        """connect signal to slot"""
        # cfg.appRestartSig.connect(self.__showRestartTooltip)

        # music in the pc
        self.downloadFolderCard.clicked.connect(self.__onDownloadFolderCardClicked)
        self.askDownloadLocationCard.checkedChanged.connect(
            self.__onAskDownloadLocationChanged
        )
        self.downloadThreadsSpinBox.valueChanged.connect(
            self.__onDownloadThreadsChanged
        )
        self.uploadThreadsSpinBox.valueChanged.connect(
            self.__onUploadThreadsChanged
        )
        self.concurrentDownloadsSpinBox.valueChanged.connect(
            self.__onConcurrentDownloadsChanged
        )
        self.concurrentUploadsSpinBox.valueChanged.connect(
            self.__onConcurrentUploadsChanged
        )
        self.retryAttemptsSpinBox.valueChanged.connect(
            self.__onRetryAttemptsChanged
        )
        self.downloadPartSizeSpinBox.valueChanged.connect(
            self.__onDownloadPartSizeChanged
        )
        self.uploadPartSizeSpinBox.valueChanged.connect(
            self.__onUploadPartSizeChanged
        )

        # personalization
        # cfg.themeChanged.connect(setTheme)
        # self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c))
        # self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged)

        # about
        self.aboutCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ABOUT_URL))
        )
