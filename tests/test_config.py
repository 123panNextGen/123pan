from src.app.common import database as database_module
from src.app.common.database import Database


def _use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "123pan-open.db"
    monkeypatch.setattr(database_module, "_get_db_path", lambda: db_path)
    Database.reset()
    return Database.instance()


def test_database_initializes_default_config(tmp_path, monkeypatch):
    db = _use_temp_db(tmp_path, monkeypatch)

    assert db.get_config("rememberPassword", None) is False
    assert db.get_config("stayLoggedIn", None) is True
    assert db.get_config("defaultDownloadPath", "")
    assert db.get_config("maxDownloadThreads", None) == 1
    assert db.get_config("retryMaxAttempts", None) == 3


def test_database_set_and_get_config(tmp_path, monkeypatch):
    db = _use_temp_db(tmp_path, monkeypatch)

    db.set_config("rememberPassword", True)
    db.set_config("retryMaxAttempts", 7)

    assert db.get_config("rememberPassword", None) is True
    assert db.get_config("retryMaxAttempts", None) == 7


def test_database_set_many_config_updates_multiple_values(tmp_path, monkeypatch):
    db = _use_temp_db(tmp_path, monkeypatch)

    db.set_many_config({
        "defaultDownloadPath": str(tmp_path / "downloads"),
        "maxConcurrentDownloads": 5,
    })

    all_config = db.get_all_config()
    assert all_config["defaultDownloadPath"] == str(tmp_path / "downloads")
    assert all_config["maxConcurrentDownloads"] == 5


class TestAutoLoginMigration:
    """测试 autoLogin 迁移到 rememberPassword + stayLoggedIn"""

    def _create_legacy_db(self, db_path, auto_login_value):
        """创建旧版 DB（schema version 1，含 autoLogin 键）"""
        import sqlite3, json
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS config "
            "(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            ("autoLogin", json.dumps(auto_login_value)),
        )
        conn.commit()
        conn.close()

    def test_migrates_auto_login_true(self, tmp_path, monkeypatch):
        db_path = tmp_path / "123pan-open.db"
        monkeypatch.setattr(database_module, "_get_db_path", lambda: db_path)
        Database.reset()

        self._create_legacy_db(db_path, True)

        Database.reset()
        db = Database.instance()

        assert db.get_config("rememberPassword", None) is True
        assert db.get_config("stayLoggedIn", None) is True
        assert db.get_config("autoLogin", "NOT_FOUND") == "NOT_FOUND"

    def test_migrates_auto_login_false(self, tmp_path, monkeypatch):
        db_path = tmp_path / "123pan-open.db"
        monkeypatch.setattr(database_module, "_get_db_path", lambda: db_path)
        Database.reset()

        self._create_legacy_db(db_path, False)

        Database.reset()
        db = Database.instance()

        assert db.get_config("rememberPassword", None) is False
        assert db.get_config("stayLoggedIn", None) is True
        assert db.get_config("autoLogin", "NOT_FOUND") == "NOT_FOUND"

    def test_no_migration_when_no_auto_login_key(self, tmp_path, monkeypatch):
        db_path = tmp_path / "123pan-open.db"
        monkeypatch.setattr(database_module, "_get_db_path", lambda: db_path)
        Database.reset()

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS config "
            "(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        Database.reset()
        db = Database.instance()

        # _init_defaults 用 INSERT OR IGNORE 设置默认值
        assert db.get_config("rememberPassword", None) is False
        assert db.get_config("stayLoggedIn", None) is True
