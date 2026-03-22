import json
import os
import platform
import sys
from pathlib import Path

from qfluentwidgets import (
    BoolValidator,
    ConfigItem,
    FolderListValidator,
    FolderValidator,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    RangeConfigItem,
    RangeValidator,
    Theme,
)

from .log import get_logger

logger = get_logger(__name__)


def isWin11():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


class Config(QConfig):
    """Config of application"""

    # folders
    musicFolders = ConfigItem("Folders", "LocalMusic", [], FolderListValidator())
    downloadFolder = ConfigItem(
        "Folders", "Download", str(Path.home() / "Downloads"), FolderValidator()
    )

    # main window
    micaEnabled = ConfigItem("MainWindow", "MicaEnabled", isWin11(), BoolValidator())
    dpiScale = OptionsConfigItem(
        "MainWindow",
        "DpiScale",
        "Auto",
        OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]),
        restart=True,
    )

    # Material
    blurRadius = RangeConfigItem(
        "Material", "AcrylicBlurRadius", 15, RangeValidator(0, 40)
    )

    # software update
    checkUpdateAtStartUp = ConfigItem(
        "Update", "CheckUpdateAtStartUp", True, BoolValidator()
    )


cfg = Config()
cfg.themeMode.value = Theme.AUTO

# 配置文件路径
if platform.system() == "Windows":
    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "Qxyz17" / "123pan"
else:
    CONFIG_DIR = Path.home() / ".config" / "Qxyz17" / "123pan"
CONFIG_FILE = CONFIG_DIR / "config.json"


class ConfigManager:
    """配置管理类"""

    @staticmethod
    def ensure_config_dir():
        """确保配置目录存在"""
        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def load_config():
        """加载配置"""
        ConfigManager.ensure_config_dir()
        default_config = {
            "userName": "",
            "passWord": "",
            "authorization": "",
            "deviceType": "",
            "osVersion": "",
            "loginuuid": "",
            "settings": {
                "defaultDownloadPath": str(Path.home() / "Downloads"),
                "askDownloadLocation": True,
            },
        }

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    # 确保新版本配置兼容性
                    if "settings" not in config:
                        config["settings"] = default_config["settings"]
                    # 兼容旧版本配置
                    for k in [
                        "userName",
                        "passWord",
                        "authorization",
                        "deviceType",
                        "osVersion",
                        "loginuuid",
                    ]:
                        if k not in config:
                            config[k] = default_config.get(k, "")
                    return config
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                # 若配置文件损坏或为空，尝试重置为默认配置
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(default_config, f, indent=2, ensure_ascii=False)
                except Exception as e2:
                    logger.error(f"重写配置失败: {e2}")
                return default_config
        return default_config

    @staticmethod
    def save_config(config):
        """保存配置"""
        try:
            ConfigManager.ensure_config_dir()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    @staticmethod
    def get_setting(key, default=None):
        """获取特定设置"""
        config = ConfigManager.load_config()
        return config.get("settings", {}).get(key, default)
