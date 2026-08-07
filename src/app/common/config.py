"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json
import sys
import threading
from pathlib import Path

from .const import CONFIG_DIR
from .database import Database
from .log import get_logger

logger = get_logger(__name__)


def isWin11():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


# 旧版 JSON 配置路径（迁移检测用，迁移后改名备份）
CONFIG_FILE = CONFIG_DIR / "config.json"

# 旧版配置中曾作为顶层字段存放的键（迁移时归入 accounts 区块）
_LEGACY_TOP_KEYS = (
    "userName",
    "passWord",
    "authorization",
    "deviceType",
    "osVersion",
    "loginuuid",
)

# 迁移守卫：按配置文件路径记录已检查/已迁移状态。
# 生产环境只 stat 一次，避免每次 get_setting 都做文件系统检查；
# 测试切换 CONFIG_FILE 路径后仍能正常触发新路径的迁移。
_MIGRATION_LOCK = threading.Lock()
_migrated_paths = set()


def _get_default_settings():
    """默认设置字典。"""
    return {
        "defaultDownloadPath": str(Path.home() / "Downloads"),
        "askDownloadLocation": True,
        "multiThreadDownload": True,
        "downloadSpeedLimit": 0,
        "uploadSpeedLimit": 0,
        "maxConcurrentUploads": 3,
        "maxConcurrentDownloads": 3,
        "proxyEnabled": False,
        "proxyType": "http",
        "proxyHost": "",
        "proxyPort": 0,
        "proxyUsername": "",
        "proxyPassword": "",
        "logLevel": "DEBUG",
        "windowOpacity": 100,
        # 系统托盘
        "closeToTray": False,      # 关闭窗口时最小化到系统托盘
        "startMinimized": False,   # 启动登录后最小化到托盘（后台同步）
    }


class ConfigManager:
    """配置管理类（SQLite 存储）。

    表结构：
        config(key TEXT PRIMARY KEY, value TEXT)   -- 设置项 + currentAccount
        accounts(...)                              -- 已保存账户
    """

    @staticmethod
    def _get_db():
        """获取数据库连接，并在首次使用时迁移旧版 JSON 配置。"""
        db = Database()
        ConfigManager._migrate_legacy_json()
        return db

    @staticmethod
    def _settings_cache():
        """获取设置项内存缓存（dict）。

        缓存绑定在当前 Database 实例上：连接被重置（Database.reset）
        或路径切换时会创建新实例，缓存随之清空，避免跨测试/跨配置污染。
        """
        return Database()._settings_cache

    @staticmethod
    def _migrate_legacy_json():
        """将旧版 config.json 迁移到 SQLite（迁移后改名备份）。

        每个配置文件路径只处理一次（生产环境仅首次调用做文件系统检查）。
        """
        global _migrated_paths
        with _MIGRATION_LOCK:
            if CONFIG_FILE in _migrated_paths:
                return
            _migrated_paths.add(CONFIG_FILE)
            if not CONFIG_FILE.exists():
                return
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                db = Database()

                # settings
                for key, value in (config.get("settings") or {}).items():
                    db.execute(
                        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                        (key, json.dumps(value, ensure_ascii=False)),
                    )

                # accounts（兼容旧格式：顶层 userName 归入 accounts 区块）
                accounts = dict(config.get("accounts") or {})
                old_user = config.get("userName", "")
                if old_user and old_user not in accounts:
                    accounts[old_user] = {
                        "userName": old_user,
                        "passWord": config.get("passWord", ""),
                        "authorization": config.get("authorization", ""),
                        "deviceType": config.get("deviceType", ""),
                        "osVersion": config.get("osVersion", ""),
                        "loginuuid": config.get("loginuuid", ""),
                    }
                for name, info in accounts.items():
                    ConfigManager._save_account_row(name, info)

                # currentAccount
                current = config.get("currentAccount", "") or old_user
                if not current and accounts:
                    current = next(iter(accounts))
                if current:
                    db.execute(
                        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                        ("currentAccount", json.dumps(current, ensure_ascii=False)),
                    )

                backup = CONFIG_FILE.with_suffix(".json.bak")
                CONFIG_FILE.rename(backup)
                logger.info("配置已从 JSON 迁移到 SQLite")
            except Exception as e:
                logger.error("迁移配置失败: %s", e)

    @staticmethod
    def _save_account_row(user_name, info):
        """写入一条账户记录（内部方法）。"""
        Database().execute(
            "INSERT OR REPLACE INTO accounts"
            " (user_name, pass_word, authorization, device_type, os_version, loginuuid)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_name,
                info.get("passWord", ""),
                info.get("authorization", ""),
                info.get("deviceType", ""),
                info.get("osVersion", ""),
                info.get("loginuuid", ""),
            ),
        )

    @staticmethod
    def ensure_config_dir():
        """确保配置目录存在。"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @staticmethod
    def load_config():
        """返回完整配置字典（兼容旧接口）。"""
        db = ConfigManager._get_db()
        settings = {}
        current = ""

        for row in db.query("SELECT key, value FROM config"):
            key = row["key"]
            try:
                val = json.loads(row["value"])
            except (ValueError, TypeError):
                val = row["value"]
            if key == "currentAccount":
                current = val or ""
            else:
                settings[key] = val

        accounts = {}
        for acc in db.query("SELECT * FROM accounts"):
            accounts[acc["user_name"]] = {
                "userName": acc["user_name"],
                "passWord": acc["pass_word"],
                "authorization": acc["authorization"],
                "deviceType": acc["device_type"],
                "osVersion": acc["os_version"],
                "loginuuid": acc["loginuuid"],
            }

        merged = _get_default_settings()
        merged.update(settings)

        # 同步到内存缓存，后续 get_setting 直接命中缓存
        cache = ConfigManager._settings_cache()
        cache.update(merged)

        return {
            "currentAccount": current,
            "accounts": accounts,
            "settings": merged,
        }

    @staticmethod
    def save_config(config):
        """将完整配置字典写入 SQLite（兼容旧接口）。"""
        # settings
        for key, value in (config.get("settings") or {}).items():
            ConfigManager.set_setting(key, value)
        # currentAccount
        current = config.get("currentAccount", "")
        ConfigManager.set_setting("currentAccount", current or "")
        # accounts
        for name, info in (config.get("accounts") or {}).items():
            ConfigManager._save_account_row(name, info)
        logger.debug("配置已保存到 SQLite")
        return True

    @staticmethod
    def get_current_account_name():
        name = ConfigManager.get_setting("currentAccount", "")
        logger.debug("当前账号: %s", name or "(无)")
        return name

    @staticmethod
    def get_account(user_name=None):
        db = ConfigManager._get_db()
        if user_name:
            row = db.query_one(
                "SELECT * FROM accounts WHERE user_name = ?", (user_name,)
            )
            logger.debug("获取账号 %s: %s", user_name, "存在" if row else "不存在")
        else:
            current = ConfigManager.get_current_account_name()
            row = (
                db.query_one(
                    "SELECT * FROM accounts WHERE user_name = ?", (current,)
                )
                if current
                else None
            )
            logger.debug(
                "获取当前账号 %s: %s", current, "存在" if row else "不存在"
            )

        if row is None:
            return {}
        account = {
            "userName": row["user_name"],
            "passWord": row["pass_word"],
            "authorization": row["authorization"],
            "deviceType": row["device_type"],
            "osVersion": row["os_version"],
            "loginuuid": row["loginuuid"],
        }
        if account.get("passWord", "").startswith("enc:"):
            from .credential import decrypt_credential

            account = dict(account)
            account["passWord"] = decrypt_credential(account["passWord"])
            logger.debug("账号密码已解密")
        return account

    @staticmethod
    def get_account_names():
        rows = ConfigManager._get_db().query(
            "SELECT user_name FROM accounts ORDER BY user_name"
        )
        names = [r["user_name"] for r in rows]
        logger.debug("已保存账号列表: %s", names)
        return names

    @staticmethod
    def save_account(user_name, account_info, set_current=True):
        info = dict(account_info)
        pwd = info.get("passWord", "")
        if pwd and not pwd.startswith("enc:"):
            from .credential import encrypt_credential

            info["passWord"] = encrypt_credential(pwd)
            logger.debug("账号密码已加密存储")

        ConfigManager._save_account_row(user_name, info)
        if set_current:
            ConfigManager.set_setting("currentAccount", user_name)
            logger.info("保存账号 %s (设为当前)", user_name)
        else:
            logger.info("保存账号 %s", user_name)
        return True

    @staticmethod
    def set_current_account(user_name):
        if user_name:
            row = ConfigManager._get_db().query_one(
                "SELECT user_name FROM accounts WHERE user_name = ?", (user_name,)
            )
            if row is None:
                logger.warning("设置当前账号失败: %s 不存在于已保存账号中", user_name)
                return False
        ConfigManager.set_setting("currentAccount", user_name or "")
        logger.info("切换当前账号为: %s", user_name or "(空)")
        return True

    @staticmethod
    def get_setting(key, default=None):
        """读取设置项（优先内存缓存，避免高频读取时的 SQLite 查询）。"""
        cache = ConfigManager._settings_cache()
        if key in cache:
            return cache[key]

        row = ConfigManager._get_db().query_one(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        if row is not None:
            try:
                val = json.loads(row["value"])
            except (ValueError, TypeError):
                val = row["value"]
            cache[key] = val
            logger.debug("读取设置 %s = %s (DB)", key, val)
            return val
        # 未存储时回退到默认设置，再回退到调用方默认值
        defaults = _get_default_settings()
        if key in defaults:
            cache[key] = defaults[key]
            return defaults[key]
        cache[key] = default
        return default

    @staticmethod
    def set_setting(key, value):
        ConfigManager._get_db().execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        # 同步更新内存缓存，保证读写一致
        ConfigManager._settings_cache()[key] = value
        logger.info("设置变更: %s = %s", key, value)
        return True
