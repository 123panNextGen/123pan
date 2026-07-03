from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFileDialog,
    QHBoxLayout, QSpinBox, QLineEdit, QComboBox,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from qfluentwidgets import (
    ExpandLayout,
    SettingCardGroup,
    PushSettingCard,
    SwitchSettingCard,
    SettingCard,
    ScrollArea,
    PrimaryPushSettingCard,
    LineEdit,
    BodyLabel,
    InfoBar
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import isWin11, ConfigManager
from ..common.const import YEAR, ABOUT_URL, VERSION
from ..common.style_sheet import StyleSheet
from ..common.log import open_log_file
from ..common.api import check_version


class _SpinBoxCard(SettingCard):
    """通用数值输入设置卡片（带 SpinBox）"""

    def __init__(self, icon, title, content, value=0, parent=None,
                 min_val=0, max_val=1048576, step=1, suffix="", special_text=""):
        super().__init__(icon, title, content, parent)
        self.spinBox = QSpinBox(self)
        self.spinBox.setRange(min_val, max_val)
        self.spinBox.setSingleStep(step)
        self.spinBox.setValue(value)
        self.spinBox.setSuffix(suffix)
        self.spinBox.setSpecialValueText(special_text)
        self.spinBox.setMinimumWidth(140)
        self.spinBox.valueChanged.connect(self._onValueChanged)
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _onValueChanged(self, val):
        """子类重写此方法以保存值。"""
        pass

    def setValue(self, val):
        self.spinBox.setValue(val)


class _SpeedLimitCard(_SpinBoxCard):
    """速度限制设置卡片"""

    def __init__(self, icon, title, content, value=0, parent=None):
        super().__init__(icon, title, content, value, parent,
                         min_val=0, max_val=1048576, step=100,
                         suffix=" KB/s", special_text="不限制")


class _ProxyHostCard(SettingCard):
    """自定义代理主机设置卡片"""

    def __init__(self, icon, title, content, text="", parent=None):
        super().__init__(icon, title, content, parent)
        self.lineEdit = LineEdit(self)
        self.lineEdit.setText(text)
        self.lineEdit.setPlaceholderText("例如: 127.0.0.1")
        self.lineEdit.setMinimumWidth(180)
        self.lineEdit.textChanged.connect(self._onTextChanged)
        self.hBoxLayout.addWidget(self.lineEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _onTextChanged(self, text):
        pass

    def text(self):
        return self.lineEdit.text()

    def setText(self, text):
        self.lineEdit.setText(text)


class _ComboCard(SettingCard):
    """自定义下拉选择卡片"""

    def __init__(self, icon, title, content, texts=None, current_index=0, parent=None):
        super().__init__(icon, title, content, parent)
        self.comboBox = QComboBox(self)
        if texts:
            self.comboBox.addItems(texts)
        self.comboBox.setCurrentIndex(current_index)
        self.comboBox.setMinimumWidth(140)
        self.hBoxLayout.addWidget(self.comboBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def currentText(self):
        return self.comboBox.currentText()

    def currentIndex(self):
        return self.comboBox.currentIndex()

class SettingInterface(ScrollArea):
    """设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        self.settingLabel = QLabel(self.tr("设置"), self)

        # ---- 下载设置组 ----
        self.downloadGroup = SettingCardGroup(
            self.tr("下载设置"), self.scrollWidget
        )
        self.downloadFolderCard = PushSettingCard(
            self.tr("选择文件夹"),
            FIF.DOWNLOAD,
            self.tr("下载目录"),
            ConfigManager.get_setting("defaultDownloadPath", str(Path.home() / "Downloads")),
            self.downloadGroup,
        )

        self.askDownloadLocationCard = SwitchSettingCard(
            FIF.DOWNLOAD,
            self.tr("每次询问下载位置"),
            self.tr("下载文件时是否每次都询问保存位置"),
            parent=self.downloadGroup,
        )
        self.askDownloadLocationCard.setChecked(
            ConfigManager.get_setting("askDownloadLocation", True)
        )

        self.multiThreadCard = SwitchSettingCard(
            FIF.SYNC,
            self.tr("多线程下载"),
            self.tr("启用多线程分片下载以提升下载速度"),
            parent=self.downloadGroup,
        )
        self.multiThreadCard.setChecked(
            ConfigManager.get_setting("multiThreadDownload", True)
        )

        self.downloadSpeedCard = _SpeedLimitCard(
            FIF.SPEED_HIGH,
            self.tr("下载限速"),
            self.tr("限制下载速度，0 表示不限制"),
            ConfigManager.get_setting("downloadSpeedLimit", 0),
            self.downloadGroup,
        )

        self.uploadSpeedCard = _SpeedLimitCard(
            FIF.SPEED_HIGH,
            self.tr("上传限速"),
            self.tr("限制上传速度，0 表示不限制"),
            ConfigManager.get_setting("uploadSpeedLimit", 0),
            self.downloadGroup,
        )

        # ---- 代理设置组 ----
        self.proxyGroup = SettingCardGroup(
            self.tr("网络代理"), self.scrollWidget
        )

        self.proxyEnabledCard = SwitchSettingCard(
            FIF.GLOBE,
            self.tr("启用代理"),
            self.tr("开启后所有网络请求将通过代理服务器"),
            parent=self.proxyGroup,
        )
        self.proxyEnabledCard.setChecked(
            ConfigManager.get_setting("proxyEnabled", False)
        )

        self.proxyTypeCard = _ComboCard(
            FIF.GLOBE,
            self.tr("代理类型"),
            self.tr("选择代理协议类型"),
            texts=["HTTP", "SOCKS5"],
            current_index=0 if ConfigManager.get_setting("proxyType", "http") == "http" else 1,
            parent=self.proxyGroup,
        )

        self.proxyHostCard = _ProxyHostCard(
            FIF.GLOBE,
            self.tr("代理主机"),
            self.tr("代理服务器地址"),
            ConfigManager.get_setting("proxyHost", ""),
            self.proxyGroup,
        )

        self.proxyPortCard = _SpinBoxCard(
            FIF.GLOBE,
            self.tr("代理端口"),
            self.tr("代理服务器端口"),
            ConfigManager.get_setting("proxyPort", 0),
            self.proxyGroup,
            min_val=0, max_val=65535, step=1,
        )

        self.proxyUserCard = _ProxyHostCard(
            FIF.PEOPLE,
            self.tr("代理用户名"),
            self.tr("代理认证用户名（可选）"),
            ConfigManager.get_setting("proxyUsername", ""),
            self.proxyGroup,
        )

        self.proxyPassCard = _ProxyHostCard(
            FIF.PEOPLE,
            self.tr("代理密码"),
            self.tr("代理认证密码（可选）"),
            ConfigManager.get_setting("proxyPassword", ""),
            self.proxyGroup,
        )

        # ---- 个性化组 ----
        self.personalGroup = SettingCardGroup(self.tr("个性化"), self.scrollWidget)
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            self.tr("Mica 效果"),
            self.tr("在窗口和表面上应用半透明效果"),
            parent=self.personalGroup,
        )
        self.micaCard.setChecked(isWin11())

        # ---- 调试组 ----
        self.debugGroup = SettingCardGroup(self.tr("调试"), self.scrollWidget)
        self.openLogFolderCard = PushSettingCard(
            self.tr("打开文件"),
            FIF.FOLDER,
            self.tr("日志文件"),
            self.tr("打开应用日志文件"),
            self.debugGroup,
        )

        # ---- 关于组 ----
        self.aboutGroup = SettingCardGroup(self.tr("关于"), self.scrollWidget)
        self.aboutCard = PrimaryPushSettingCard(
            self.tr("项目页面"),
            FIF.INFO,
            self.tr("关于"),
            "123pan" + f"{VERSION}" + " © Copyright" + f" {YEAR}",
            self.aboutGroup,
        )
        self.checkversion = PushSettingCard(
            self.tr("检查"),
            FIF.FOLDER,
            self.tr("检查更新"),
            self.tr("检查当前应用是否为最新版"),
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

        self.scrollWidget.setObjectName("scrollWidget")
        self.settingLabel.setObjectName("settingLabel")
        StyleSheet.SETTING_INTERFACE.apply(self)

        self.micaCard.setEnabled(isWin11())

        self.__initLayout()
        self.__connectSignalToSlot()

    def __initLayout(self):
        self.settingLabel.move(36, 30)

        # 下载设置组
        self.downloadGroup.addSettingCard(self.downloadFolderCard)
        self.downloadGroup.addSettingCard(self.askDownloadLocationCard)
        self.downloadGroup.addSettingCard(self.multiThreadCard)
        self.downloadGroup.addSettingCard(self.downloadSpeedCard)
        self.downloadGroup.addSettingCard(self.uploadSpeedCard)

        # 代理设置组
        self.proxyGroup.addSettingCard(self.proxyEnabledCard)
        self.proxyGroup.addSettingCard(self.proxyTypeCard)
        self.proxyGroup.addSettingCard(self.proxyHostCard)
        self.proxyGroup.addSettingCard(self.proxyPortCard)
        self.proxyGroup.addSettingCard(self.proxyUserCard)
        self.proxyGroup.addSettingCard(self.proxyPassCard)

        # 个性化组
        self.personalGroup.addSettingCard(self.micaCard)

        # 调试组
        self.debugGroup.addSettingCard(self.openLogFolderCard)

        # 关于组
        self.aboutGroup.addSettingCard(self.aboutCard)
        self.aboutGroup.addSettingCard(self.checkversion)

        # 添加到布局
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.downloadGroup)
        self.expandLayout.addWidget(self.proxyGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.debugGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    # ---- 事件处理 ----

    def check(self):
        if check_version():
            InfoBar.success(title="检查成功", content="当前是最新版本", parent=self)
        else:
            InfoBar.error(title="检查失败", content="当前不是最新版本，或当前无法完成检查", parent=self)    

    def __onDownloadFolderCardClicked(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose folder"), "./")
        if not folder or ConfigManager.get_setting("defaultDownloadPath") == folder:
            return
        self.downloadFolderCard.setContent(folder)
        ConfigManager.set_setting("defaultDownloadPath", folder)

    def __onAskDownloadLocationChanged(self, checked):
        ConfigManager.set_setting("askDownloadLocation", checked)

    def __onMultiThreadChanged(self, checked):
        ConfigManager.set_setting("multiThreadDownload", checked)
        # 实时应用到当前 session
        if self.parent() and hasattr(self.parent(), 'pan'):
            self.parent().pan._session.set_multi_thread(checked)

    def __onDownloadSpeedChanged(self, val):
        ConfigManager.set_setting("downloadSpeedLimit", val)

    def __onUploadSpeedChanged(self, val):
        ConfigManager.set_setting("uploadSpeedLimit", val)

    def __onProxyEnabledChanged(self, checked):
        ConfigManager.set_setting("proxyEnabled", checked)

    def __onProxyTypeChanged(self, text):
        proxy_type = "http" if text == "HTTP" else "socks5"
        ConfigManager.set_setting("proxyType", proxy_type)

    def __onProxyHostChanged(self, text):
        ConfigManager.set_setting("proxyHost", text)

    def __onProxyPortChanged(self, val):
        ConfigManager.set_setting("proxyPort", val)

    def __onProxyUserChanged(self, text):
        ConfigManager.set_setting("proxyUsername", text)

    def __onProxyPassChanged(self, text):
        ConfigManager.set_setting("proxyPassword", text)

    def __connectSignalToSlot(self):
        # 下载设置
        self.downloadFolderCard.clicked.connect(self.__onDownloadFolderCardClicked)
        self.askDownloadLocationCard.checkedChanged.connect(
            self.__onAskDownloadLocationChanged
        )
        self.multiThreadCard.checkedChanged.connect(self.__onMultiThreadChanged)
        self.downloadSpeedCard.spinBox.valueChanged.connect(
            self.__onDownloadSpeedChanged
        )
        self.uploadSpeedCard.spinBox.valueChanged.connect(
            self.__onUploadSpeedChanged
        )

        # 代理设置
        self.proxyEnabledCard.checkedChanged.connect(self.__onProxyEnabledChanged)
        self.proxyTypeCard.comboBox.currentTextChanged.connect(self.__onProxyTypeChanged)

        # 代理主机 - 使用 editingFinished 而不是每次字符变化都触发
        self.proxyHostCard.lineEdit.editingFinished.connect(
            lambda: self.__onProxyHostChanged(self.proxyHostCard.text())
        )
        self.proxyPortCard.spinBox.valueChanged.connect(self.__onProxyPortChanged)

        self.proxyUserCard.lineEdit.editingFinished.connect(
            lambda: self.__onProxyUserChanged(self.proxyUserCard.text())
        )
        self.proxyPassCard.lineEdit.editingFinished.connect(
            lambda: self.__onProxyPassChanged(self.proxyPassCard.text())
        )

        # 调试
        self.openLogFolderCard.clicked.connect(lambda: open_log_file())

        # 关于
        self.aboutCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ABOUT_URL))
        )
        self.checkversion.clicked.connect(
            lambda: self.check()
        )
