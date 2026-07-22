"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from src.app.common.config import ConfigManager


class TestConfigManager:
    def test_load_default_config(self, tmp_path):
        """配置不存在时返回默认配置。"""
        import src.app.common.config as config_mod
        config_mod.CONFIG_DIR = tmp_path / "123pan"
        config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"

        config = ConfigManager.load_config()
        assert config["currentAccount"] == ""
        assert config["accounts"] == {}
        assert config["settings"]["downloadSpeedLimit"] == 0
        assert config["settings"]["multiThreadDownload"] is True

    def test_save_and_load_config(self, tmp_path):
        """保存后能正确加载。"""
        import src.app.common.config as config_mod
        config_mod.CONFIG_DIR = tmp_path / "123pan"
        config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"

        config = ConfigManager.load_config()
        config["settings"]["downloadSpeedLimit"] = 500
        assert ConfigManager.save_config(config) is True

        config2 = ConfigManager.load_config()
        assert config2["settings"]["downloadSpeedLimit"] == 500

    def test_setting_read_write(self, tmp_path):
        """get_setting / set_setting 读写正常。"""
        import src.app.common.config as config_mod
        config_mod.CONFIG_DIR = tmp_path / "123pan"
        config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"

        assert ConfigManager.get_setting("downloadSpeedLimit") == 0
        assert ConfigManager.get_setting("nonexistent", "fallback") == "fallback"

        ConfigManager.set_setting("downloadSpeedLimit", 1000)
        assert ConfigManager.get_setting("downloadSpeedLimit") == 1000

    def test_account_lifecycle(self, tmp_path):
        """保存账号、获取账号、切换账号完整流程。"""
        import src.app.common.config as config_mod
        config_mod.CONFIG_DIR = tmp_path / "123pan"
        config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"

        # initially no accounts
        assert ConfigManager.get_account_names() == []

        # save account
        account_info = {"userName": "test_user", "passWord": "my_password", "authorization": "tok_xxx"}
        assert ConfigManager.save_account("test_user", account_info) is True

        # verify account name appears
        assert ConfigManager.get_account_names() == ["test_user"]

        # verify current account is set
        assert ConfigManager.get_current_account_name() == "test_user"

        # verify password is encrypted on disk
        import json
        with open(config_mod.CONFIG_FILE, "r") as f:
            raw = json.load(f)
        stored_pwd = raw["accounts"]["test_user"]["passWord"]
        assert stored_pwd.startswith("enc:")

        # verify get_account decrypts automatically
        account = ConfigManager.get_account("test_user")
        assert account["passWord"] == "my_password"

        # switch account
        ConfigManager.save_account("user2", {"userName": "user2", "passWord": "pwd2"})
        ConfigManager.set_current_account("user2")
        assert ConfigManager.get_current_account_name() == "user2"

    def test_set_current_account_nonexistent(self, tmp_path):
        """切换到不存在的账号返回 False。"""
        import src.app.common.config as config_mod
        config_mod.CONFIG_DIR = tmp_path / "123pan"
        config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"

        assert ConfigManager.set_current_account("nonexistent") is False

    def test_old_format_migration(self, tmp_path):
        """旧格式配置文件自动迁移到新格式。"""
        import src.app.common.config as config_mod
        config_mod.CONFIG_DIR = tmp_path / "123pan"
        config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"

        config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        old_config = {
            "userName": "old_user",
            "passWord": "old_pwd",
            "authorization": "old_tok",
        }
        import json
        with open(config_mod.CONFIG_FILE, "w") as f:
            json.dump(old_config, f)

        config = ConfigManager.load_config()
        # old top-level fields should be migrated
        assert config["currentAccount"] == "old_user"
        assert "old_user" in config["accounts"]
        # migration preserves old password as-is (not encrypted)
        assert config["accounts"]["old_user"]["passWord"] == "old_pwd"
        # old top-level fields cleaned up
        assert "userName" not in config
        assert "passWord" not in config
        # settings should have defaults
        assert "settings" in config
        assert config["settings"]["downloadSpeedLimit"] == 0
