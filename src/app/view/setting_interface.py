from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QFileDialog,
    QHBoxLayout,
    QSpinBox,
    QLineEdit,
    QComboBox,
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
    InfoBar,
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import isWin11, ConfigManager
from ..common.const import YEAR, ABOUT_URL, VERSION
from ..common.style_sheet import StyleSheet
from ..common.log import get_logger, open_log_file, set_log_level, get_level_names
from ..common.api import check_version
from ..common.i18n import tr

logger = get_logger(__name__)


class _SpinBoxCard(SettingCard):
    """通用数值输入设置卡片（带 SpinBox）"""

    def __init__(
        self,
        icon,
        title,
        content,
        value=0,
        parent=None,
        min_val=0,
        max_val=1048576,
        step=1,
        suffix="",
        special_text="",
    ):
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
        super().__init__(
            icon,
            title,
            content,
            value,
            parent,
            min_val=0,
            max_val=1048576,
            step=100,
            suffix=" KB/s",
            special_text=tr("settings.speed_unlimited", "不限制"),
        )


class _ProxyHostCard(SettingCard):
    """自定义代理主机设置卡片"""

    def __init__(self, icon, title, content, text="", parent=None):
        super().__init__(icon, title, content, parent)
        self.lineEdit = LineEdit(self)
        self.lineEdit.setText(text)
        self.lineEdit.setPlaceholderText(tr("settings.proxy_host_placeholder", "例如: 127.0.0.1"))
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

        self.settingLabel = QLabel(tr("settings.title", "设置"), self)

        # ---- 下载设置组 ----
        self.downloadGroup = SettingCardGroup(tr("settings.group_download", "下载设置"), self.scrollWidget)
        self.downloadFolderCard = PushSettingCard(
            tr("settings.download_folder", "选择文件夹"),
            FIF.DOWNLOAD,
            tr("settings.download_dir", "下载目录"),
            ConfigManager.get_setting(
                "defaultDownloadPath", str(Path.home() / "Downloads")
            ),
            self.downloadGroup,
        )

        self.askDownloadLocationCard = SwitchSettingCard(
            FIF.DOWNLOAD,
            tr("settings.ask_download", "每次询问下载位置"),
            tr("settings.ask_download_desc", "下载文件时是否每次都询问保存位置"),
            parent=self.downloadGroup,
        )
        self.askDownloadLocationCard.setChecked(
            ConfigManager.get_setting("askDownloadLocation", True)
        )

        self.multiThreadCard = SwitchSettingCard(
            FIF.SYNC,
            tr("settings.multi_thread", "多线程下载"),
            tr("settings.multi_thread_desc", "启用多线程分片下载以提升下载速度"),
            parent=self.downloadGroup,
        )
        self.multiThreadCard.setChecked(
            ConfigManager.get_setting("multiThreadDownload", True)
        )

        self.downloadSpeedCard = _SpeedLimitCard(
            FIF.SPEED_HIGH,
            tr("下载限速"),
            tr("限制下载速度，0 表示不限制"),
            ConfigManager.get_setting("downloadSpeedLimit", 0),
            self.downloadGroup,
        )

        self.uploadSpeedCard = _SpeedLimitCard(
            FIF.SPEED_HIGH,
            tr("上传限速"),
            tr("限制上传速度，0 表示不限制"),
            ConfigManager.get_setting("uploadSpeedLimit", 0),
            self.downloadGroup,
        )

        # ---- 代理设置组 ----
        self.proxyGroup = SettingCardGroup(tr("网络代理"), self.scrollWidget)

        self.proxyEnabledCard = SwitchSettingCard(
            FIF.GLOBE,
            tr("启用代理"),
            tr("开启后所有网络请求将通过代理服务器"),
            parent=self.proxyGroup,
        )
        self.proxyEnabledCard.setChecked(
            ConfigManager.get_setting("proxyEnabled", False)
        )

        self.proxyTypeCard = _ComboCard(
            FIF.GLOBE,
            tr("代理类型"),
            tr("选择代理协议类型"),
            texts=["HTTP", "SOCKS5"],
            current_index=(
                0 if ConfigManager.get_setting("proxyType", "http") == "http" else 1
            ),
            parent=self.proxyGroup,
        )

        self.proxyHostCard = _ProxyHostCard(
            FIF.GLOBE,
            tr("代理主机"),
            tr("代理服务器地址"),
            ConfigManager.get_setting("proxyHost", ""),
            self.proxyGroup,
        )

        self.proxyPortCard = _SpinBoxCard(
            FIF.GLOBE,
            tr("代理端口"),
            tr("代理服务器端口"),
            ConfigManager.get_setting("proxyPort", 0),
            self.proxyGroup,
            min_val=0,
            max_val=65535,
            step=1,
        )

        self.proxyUserCard = _ProxyHostCard(
            FIF.PEOPLE,
            tr("代理用户名"),
            tr("代理认证用户名（可选）"),
            ConfigManager.get_setting("proxyUsername", ""),
            self.proxyGroup,
        )

        self.proxyPassCard = _ProxyHostCard(
            FIF.PEOPLE,
            tr("代理密码"),
            tr("代理认证密码（可选）"),
            ConfigManager.get_setting("proxyPassword", ""),
            self.proxyGroup,
        )

        # ---- 个性化组 ----
        self.personalGroup = SettingCardGroup(tr("个性化"), self.scrollWidget)
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            tr("Mica 效果"),
            tr("在窗口和表面上应用半透明效果"),
            parent=self.personalGroup,
        )
        self.micaCard.setChecked(isWin11())

        self.languageCard = _ComboCard(
            FIF.LANGUAGE,
            tr("界面语言"),
            tr("选择应用程序的显示语言"),
            texts=[tr("settings.lang_zh", "简体中文"), tr("settings.lang_en", "English")],
            current_index=(
                0 if ConfigManager.get_setting("language", "zh_CN") == "zh_CN" else 1
            ),
            parent=self.personalGroup,
        )

        # ---- 调试组 ----
        self.debugGroup = SettingCardGroup(tr("调试"), self.scrollWidget)

        _saved_level = ConfigManager.get_setting("logLevel", "DEBUG")
        _level_names = get_level_names()
        _current_idx = _level_names.index(_saved_level) if _saved_level in _level_names else 0

        self.logLevelCard = _ComboCard(
            FIF.FLAG,
            tr("日志等级"),
            tr("设置日志输出详细程度"),
            texts=_level_names,
            current_index=_current_idx,
            parent=self.debugGroup,
        )

        self.openLogFolderCard = PushSettingCard(
            tr("打开文件"),
            FIF.FOLDER,
            tr("日志文件"),
            tr("打开应用日志文件"),
            self.debugGroup,
        )

        self.clearCacheCard = PushSettingCard(
            tr("清除"),
            FIF.DELETE,
            tr("清理缓存"),
            tr("清除临时下载文件和缓存数据"),
            self.debugGroup,
        )

        self.refreshFileDbCard = PushSettingCard(
            tr("刷新"),
            FIF.SYNC,
            tr("强制刷新文件列表"),
            tr("清除本地文件列表缓存，下次浏览时从服务器重新获取"),
            self.debugGroup,
        )

        self.deleteFileDbCard = PushSettingCard(
            tr("删除"),
            FIF.REMOVE,
            tr("删除文件列表数据库"),
            tr("完全删除本地文件列表数据库，下次启动时重建"),
            self.debugGroup,
        )

        # ---- 关于组 ----
        self.aboutGroup = SettingCardGroup(tr("关于"), self.scrollWidget)
        self.aboutCard = PrimaryPushSettingCard(
            tr("项目页面"),
            FIF.INFO,
            tr("关于"),
            "123pan" + f"{VERSION}" + " © Copyright" + f" {YEAR}",
            self.aboutGroup,
        )
        self.checkversion = PushSettingCard(
            tr("检查"),
            FIF.FOLDER,
            tr("检查更新"),
            tr("检查当前应用是否为最新版"),
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
        self.personalGroup.addSettingCard(self.languageCard)

        # 调试组
        self.debugGroup.addSettingCard(self.logLevelCard)
        self.debugGroup.addSettingCard(self.openLogFolderCard)
        self.debugGroup.addSettingCard(self.clearCacheCard)
        self.debugGroup.addSettingCard(self.refreshFileDbCard)
        self.debugGroup.addSettingCard(self.deleteFileDbCard)

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

    def __onLanguageChanged(self, text):
        """语言切换"""
        lang_code = "zh_CN" if text == tr("settings.lang_zh", "简体中文") else "en_US"
        ConfigManager.set_setting("language", lang_code)
        logger.info("界面语言切换为: %s (%s)", text, lang_code)
        InfoBar.info(
            title=tr("settings.msg_lang_restart", "语言设置"),
            content=tr("settings.msg_lang_restart_desc", "语言设置将在重启应用后生效"),
            parent=self,
        )

    def __onClearCacheClicked(self):
        """清理缓存（临时文件和下载残留）"""
        import shutil
        from pathlib import Path

        temp_dir = Path.home() / ".cache" / "123pan" / "temp"
        download_dir = Path(
            ConfigManager.get_setting(
                "defaultDownloadPath", str(Path.home() / "Downloads")
            )
        )

        cleaned_count = 0
        cleaned_size = 0

        # 清理临时目录
        if temp_dir.exists():
            for f in temp_dir.glob("*.tmp"):
                try:
                    cleaned_size += f.stat().st_size
                    f.unlink()
                    cleaned_count += 1
                except OSError:
                    pass
            for f in temp_dir.glob("*.part*"):
                try:
                    cleaned_size += f.stat().st_size
                    f.unlink()
                    cleaned_count += 1
                except OSError:
                    pass

        # 清理下载目录中的 .tmp 文件
        if download_dir.exists():
            for f in download_dir.glob("*.tmp"):
                try:
                    cleaned_size += f.stat().st_size
                    f.unlink()
                    cleaned_count += 1
                except OSError:
                    pass

        if cleaned_count > 0:
            from ..common.utils import format_file_size
            InfoBar.success(
                title=tr("settings.msg_cache_cleaned", "清理完成"),
                content=tr("settings.msg_cache_cleaned_desc", "已清理 {} 个临时文件，释放 {}").format(
                    cleaned_count, format_file_size(cleaned_size)
                ),
                parent=self,
            )
            logger.info(
                "缓存清理完成: %d 个文件, %s",
                cleaned_count,
                format_file_size(cleaned_size),
            )
        else:
            InfoBar.info(
                title=tr("settings.msg_no_cache", "无需清理"),
                content=tr("settings.msg_no_cache_desc", "没有找到可清理的临时文件"),
                parent=self,
            )

    def __onRefreshFileDbClicked(self):
        """强制刷新文件列表数据库（标记所有目录为脏）。"""
        from ..common.file_list_db import FileListDB
        db = FileListDB()
        dir_count, file_count = db.get_stats()
        db.mark_all_dirty()
        logger.info("已标记 %d 个目录为脏，共 %d 个文件缓存", dir_count, file_count)
        InfoBar.success(
            title=tr("settings.msg_db_refresh", "刷新中"),
            content=tr(
                "settings.msg_db_refresh_desc",
                "已标记 {} 个目录缓存为待刷新，下次浏览时将重新加载"
            ).format(dir_count),
            parent=self,
        )

    def __onDeleteFileDbClicked(self):
        """删除文件列表数据库。"""
        from ..common.file_list_db import FileListDB
        db = FileListDB()
        dir_count, file_count = db.get_stats()
        db.delete_db()
        logger.info("文件列表数据库已删除: %d 个目录, %d 个文件", dir_count, file_count)
        InfoBar.success(
            title=tr("settings.msg_db_deleted", "已删除"),
            content=tr(
                "settings.msg_db_deleted_desc",
                "已删除本地文件列表数据库（{} 个目录, {} 个文件缓存），下次启动时将重建"
            ).format(dir_count, file_count),
            parent=self,
        )

    # ---- 事件处理 ----

    def check(self):
        if check_version():
            InfoBar.success(
                title=tr("settings.msg_check_success", "检查成功"),
                content=tr("settings.msg_latest_version", "当前是最新版本"),
                parent=self,
            )
        else:
            InfoBar.error(
                title=tr("settings.msg_check_failed", "检查失败"),
                content=tr("settings.msg_not_latest", "当前不是最新版本，或当前无法完成检查"),
                parent=self,
            )

    def __onDownloadFolderCardClicked(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("settings.choose_folder", "Choose folder"), "./"
        )
        if not folder or ConfigManager.get_setting("defaultDownloadPath") == folder:
            return
        self.downloadFolderCard.setContent(folder)
        ConfigManager.set_setting("defaultDownloadPath", folder)
        logger.info("下载目录变更为: %s", folder)

    def __onAskDownloadLocationChanged(self, checked):
        ConfigManager.set_setting("askDownloadLocation", checked)
        logger.info("询问下载位置: %s", "开启" if checked else "关闭")

    def __onMultiThreadChanged(self, checked):
        ConfigManager.set_setting("multiThreadDownload", checked)
        if self.parent() and hasattr(self.parent(), "pan"):
            self.parent().pan.set_download_multi_thread(checked)
        logger.info("多线程下载: %s", "开启" if checked else "关闭")

    def __onDownloadSpeedChanged(self, val):
        ConfigManager.set_setting("downloadSpeedLimit", val)
        if self.parent() and hasattr(self.parent(), "pan"):
            self.parent().pan.set_download_speed_limit(val)
        logger.info("下载限速: %d KB/s", val)

    def __onUploadSpeedChanged(self, val):
        ConfigManager.set_setting("uploadSpeedLimit", val)
        if self.parent() and hasattr(self.parent(), "pan"):
            self.parent().pan.set_upload_speed_limit(val)
        logger.info("上传限速: %d KB/s", val)

    def _apply_proxy_to_service(self):
        """将当前代理配置推送到 Service。"""
        if not (self.parent() and hasattr(self.parent(), "pan")):
            return
        enabled = ConfigManager.get_setting("proxyEnabled", False)
        if enabled:
            proxy_type = ConfigManager.get_setting("proxyType", "http")
            host = ConfigManager.get_setting("proxyHost", "")
            port = ConfigManager.get_setting("proxyPort", 0)
            username = ConfigManager.get_setting("proxyUsername", "")
            password = ConfigManager.get_setting("proxyPassword", "")
            if host and port > 0:
                self.parent().pan.set_download_proxy(
                    proxy_type, host, port, username, password
                )
                return
        self.parent().pan.clear_download_proxy()

    def __onProxyEnabledChanged(self, checked):
        ConfigManager.set_setting("proxyEnabled", checked)
        self._apply_proxy_to_service()
        logger.info("代理: %s", "开启" if checked else "关闭")

    def __onProxyTypeChanged(self, text):
        proxy_type = "http" if text == "HTTP" else "socks5"
        ConfigManager.set_setting("proxyType", proxy_type)
        self._apply_proxy_to_service()
        logger.info("代理类型: %s", proxy_type)

    def __onProxyHostChanged(self, text):
        ConfigManager.set_setting("proxyHost", text)
        self._apply_proxy_to_service()
        logger.debug("代理主机: %s", text)

    def __onProxyPortChanged(self, val):
        ConfigManager.set_setting("proxyPort", val)
        self._apply_proxy_to_service()
        logger.debug("代理端口: %d", val)

    def __onProxyUserChanged(self, text):
        ConfigManager.set_setting("proxyUsername", text)
        self._apply_proxy_to_service()
        logger.debug("代理用户名: %s", text)

    def __onProxyPassChanged(self, text):
        ConfigManager.set_setting("proxyPassword", text)
        self._apply_proxy_to_service()
        logger.debug("代理密码已更新")

    def __onLogLevelChanged(self, level_name):
        ConfigManager.set_setting("logLevel", level_name)
        set_log_level(level_name)
        logger.info("日志等级切换为: %s", level_name)

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
        self.uploadSpeedCard.spinBox.valueChanged.connect(self.__onUploadSpeedChanged)

        # 代理设置
        self.proxyEnabledCard.checkedChanged.connect(self.__onProxyEnabledChanged)
        self.proxyTypeCard.comboBox.currentTextChanged.connect(
            self.__onProxyTypeChanged
        )

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
        self.logLevelCard.comboBox.currentTextChanged.connect(
            self.__onLogLevelChanged
        )
        self.openLogFolderCard.clicked.connect(lambda: open_log_file())
        self.clearCacheCard.clicked.connect(self.__onClearCacheClicked)
        self.refreshFileDbCard.clicked.connect(self.__onRefreshFileDbClicked)
        self.deleteFileDbCard.clicked.connect(self.__onDeleteFileDbClicked)

        # 个性化
        self.languageCard.comboBox.currentTextChanged.connect(
            self.__onLanguageChanged
        )

        # 关于
        self.aboutCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ABOUT_URL))
        )
        self.checkversion.clicked.connect(lambda: self.check())
