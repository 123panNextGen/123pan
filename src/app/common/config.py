import json
import os
import platform
import sys
from pathlib import Path
from .log import get_logger

logger = get_logger(__name__)


def isWin11():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


# 配置文件路径
if platform.system() == "Windows":
    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "123pan"
else:
    CONFIG_DIR = Path.home() / ".config" / "123pan"
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
            "currentAccount": "",
            "accounts": {},
            "settings": {
                "defaultDownloadPath": str(Path.home() / "Downloads"),
                "askDownloadLocation": True,
                # 多线程下载开关
                "multiThreadDownload": True,
                # 速度限制（0 表示不限制，单位 KB/s）
                "downloadSpeedLimit": 0,
                "uploadSpeedLimit": 0,
                # 代理配置
                "proxyEnabled": False,
                "proxyType": "http",
                "proxyHost": "",
                "proxyPort": 0,
                "proxyUsername": "",
                "proxyPassword": "",
            },
        }

        if CONFIG_FILE.exists():
            migrated = False
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    # 兼容旧版本配置
                    if "settings" not in config:
                        config["settings"] = default_config["settings"]
                        migrated = True

                    if "accounts" not in config:
                        config["accounts"] = {}

                    old_user = config.get("userName", "")
                    if old_user:
                        config["accounts"].setdefault(old_user, {
                            "userName": old_user,
                            "passWord": config.get("passWord", ""),
                            "authorization": config.get("authorization", ""),
                            "deviceType": config.get("deviceType", ""),
                            "osVersion": config.get("osVersion", ""),
                            "loginuuid": config.get("loginuuid", ""),
                        })
                        migrated = True

                    if "currentAccount" not in config or not config.get("currentAccount", ""):
                        config["currentAccount"] = config.get("userName", "")
                        if not config["currentAccount"] and config["accounts"]:
                            config["currentAccount"] = next(iter(config["accounts"]))
                        migrated = True

                    # 删除重复的顶层账号字段，只保留 accounts 区块
                    for k in [
                        "userName",
                        "passWord",
                        "authorization",
                        "deviceType",
                        "osVersion",
                        "loginuuid",
                    ]:
                        if k in config:
                            del config[k]
                            migrated = True

                    # 补齐缺失的 settings 默认值
                    for key, val in default_config["settings"].items():
                        if key not in config.get("settings", {}):
                            config["settings"][key] = val
                            migrated = True

                    if migrated:
                        ConfigManager.save_config(config)
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
    def get_current_account_name():
        config = ConfigManager.load_config()
        return config.get("currentAccount", "")

    @staticmethod
    def get_account(user_name=None):
        config = ConfigManager.load_config()
        accounts = config.get("accounts", {})
        if user_name:
            account = accounts.get(user_name, {})
        else:
            current = config.get("currentAccount", "")
            account = accounts.get(current, {})

        # 解密密码（惰性导入避免循环依赖）
        if account and account.get("passWord", "").startswith("enc:"):
            from .credential import decrypt_credential
            account = dict(account)
            account["passWord"] = decrypt_credential(account["passWord"])
        return account

    @staticmethod
    def get_account_names():
        return list(ConfigManager.load_config().get("accounts", {}).keys())

    @staticmethod
    def save_account(user_name, account_info, set_current=True):
        config = ConfigManager.load_config()
        if "accounts" not in config:
            config["accounts"] = {}

        # 加密密码后存储（惰性导入避免循环依赖）
        info = dict(account_info)
        pwd = info.get("passWord", "")
        if pwd and not pwd.startswith("enc:"):
            from .credential import encrypt_credential
            info["passWord"] = encrypt_credential(pwd)

        config["accounts"][user_name] = info
        if set_current:
            config["currentAccount"] = user_name
        return ConfigManager.save_config(config)

    @staticmethod
    def set_current_account(user_name):
        config = ConfigManager.load_config()
        if user_name and user_name not in config.get("accounts", {}):
            return False
        config["currentAccount"] = user_name
        return ConfigManager.save_config(config)

    @staticmethod
    def get_setting(key, default=None):
        """获取特定设置"""
        config = ConfigManager.load_config()
        if key in config.get("settings", {}):
            return config["settings"][key]

        if key in [
            "userName",
            "passWord",
            "authorization",
            "deviceType",
            "osVersion",
            "loginuuid",
        ]:
            account = ConfigManager.get_account()
            if account:
                return account.get(key, default)

        return config.get(key, default)

    @staticmethod
    def set_setting(key, value):
        """设置特定设置项并保存"""
        config = ConfigManager.load_config()
        if "settings" not in config:
            config["settings"] = {}
        config["settings"][key] = value
        return ConfigManager.save_config(config)
