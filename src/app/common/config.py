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
                # 日志等级
                "logLevel": "DEBUG",
            },
        }

        if CONFIG_FILE.exists():
            migrated = False
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    logger.debug(
                        "配置文件已加载: %s (%d KB)",
                        CONFIG_FILE,
                        CONFIG_FILE.stat().st_size // 1024,
                    )
                    # 兼容旧版本配置
                    if "settings" not in config:
                        config["settings"] = default_config["settings"]
                        migrated = True
                        logger.info("配置迁移: 补全 settings 字段")

                    if "accounts" not in config:
                        config["accounts"] = {}

                    old_user = config.get("userName", "")
                    if old_user:
                        config["accounts"].setdefault(
                            old_user,
                            {
                                "userName": old_user,
                                "passWord": config.get("passWord", ""),
                                "authorization": config.get("authorization", ""),
                                "deviceType": config.get("deviceType", ""),
                                "osVersion": config.get("osVersion", ""),
                                "loginuuid": config.get("loginuuid", ""),
                            },
                        )
                        migrated = True
                        logger.info(
                            "配置迁移: 将旧账号 %s 迁移到 accounts 区块", old_user
                        )

                    if "currentAccount" not in config or not config.get(
                        "currentAccount", ""
                    ):
                        config["currentAccount"] = config.get("userName", "")
                        if not config["currentAccount"] and config["accounts"]:
                            config["currentAccount"] = next(iter(config["accounts"]))
                        migrated = True
                        logger.info(
                            "配置迁移: 补全 currentAccount=%s", config["currentAccount"]
                        )

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
                            logger.info("配置迁移: 删除冗余顶层字段 %s", k)

                    for key, val in default_config["settings"].items():
                        if key not in config.get("settings", {}):
                            config["settings"][key] = val
                            migrated = True
                            logger.info("配置迁移: 补全默认设置 %s=%s", key, val)

                    if migrated:
                        ConfigManager.save_config(config)
                    return config
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(default_config, f, indent=2, ensure_ascii=False)
                    logger.info("配置文件已重置为默认值")
                except Exception as e2:
                    logger.error(f"重写配置失败: {e2}")
                return default_config
        logger.debug("配置文件不存在，使用默认配置")
        return default_config

    @staticmethod
    def save_config(config):
        """保存配置"""
        try:
            ConfigManager.ensure_config_dir()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.debug("配置已保存到 %s", CONFIG_FILE)
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    @staticmethod
    def get_current_account_name():
        config = ConfigManager.load_config()
        name = config.get("currentAccount", "")
        logger.debug("当前账号: %s", name or "(无)")
        return name

    @staticmethod
    def get_account(user_name=None):
        config = ConfigManager.load_config()
        accounts = config.get("accounts", {})
        if user_name:
            account = accounts.get(user_name, {})
            logger.debug("获取账号 %s: %s", user_name, "存在" if account else "不存在")
        else:
            current = config.get("currentAccount", "")
            account = accounts.get(current, {})
            logger.debug(
                "获取当前账号 %s: %s", current, "存在" if account else "不存在"
            )

        if account and account.get("passWord", "").startswith("enc:"):
            from .credential import decrypt_credential

            account = dict(account)
            account["passWord"] = decrypt_credential(account["passWord"])
            logger.debug("账号密码已解密")
        return account

    @staticmethod
    def get_account_names():
        names = list(ConfigManager.load_config().get("accounts", {}).keys())
        logger.debug("已保存账号列表: %s", names)
        return names

    @staticmethod
    def save_account(user_name, account_info, set_current=True):
        config = ConfigManager.load_config()
        if "accounts" not in config:
            config["accounts"] = {}
            logger.debug("初始化 accounts 区块")

        info = dict(account_info)
        pwd = info.get("passWord", "")
        if pwd and not pwd.startswith("enc:"):
            from .credential import encrypt_credential

            info["passWord"] = encrypt_credential(pwd)
            logger.debug("账号密码已加密存储")

        config["accounts"][user_name] = info
        if set_current:
            config["currentAccount"] = user_name
            logger.info("保存账号 %s (设为当前)", user_name)
        else:
            logger.info("保存账号 %s", user_name)
        return ConfigManager.save_config(config)

    @staticmethod
    def set_current_account(user_name):
        config = ConfigManager.load_config()
        if user_name and user_name not in config.get("accounts", {}):
            logger.warning("设置当前账号失败: %s 不存在于已保存账号中", user_name)
            return False
        config["currentAccount"] = user_name
        logger.info("切换当前账号为: %s", user_name or "(空)")
        return ConfigManager.save_config(config)

    @staticmethod
    def get_setting(key, default=None):
        config = ConfigManager.load_config()
        settings = config.get("settings", {})
        val = settings.get(key, default)
        logger.debug("读取设置 %s = %s", key, val)
        return val

    @staticmethod
    def set_setting(key, value):
        config = ConfigManager.load_config()
        if "settings" not in config:
            config["settings"] = {}
        config["settings"][key] = value
        logger.info("设置变更: %s = %s", key, value)
        return ConfigManager.save_config(config)
