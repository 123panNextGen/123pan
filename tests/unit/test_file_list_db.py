"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json

from src.app.common.database import Database
from src.app.common.file_list_db import FileListDB


def _file(fid, name="file.txt"):
    return {
        "FileId": fid,
        "FileName": name,
        "Type": 0,
        "Size": 100,
    }


class TestFileListDB:
    def test_save_and_get_dir(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1), _file(2)], total=2, all_loaded=True)
        files, total, all_loaded = db.get_dir(0)
        assert total == 2
        assert all_loaded is True
        assert [f["FileId"] for f in files] == [1, 2]

    def test_get_dir_missing(self, tmp_db):
        db = FileListDB()
        assert db.get_dir(999) == (None, 0, False)

    def test_save_dir_string_id(self, tmp_db):
        db = FileListDB()
        db.save_dir("123", [_file(1)], total=1)
        files, total, _ = db.get_dir("123")
        assert files[0]["FileId"] == 1
        assert total == 1

    def test_accounts_use_separate_tables(self, tmp_db):
        first = FileListDB("first@example.com")
        second = FileListDB("second@example.com")

        first.save_dir(0, [_file(1, "first.txt")], total=1)
        second.save_dir(0, [_file(2, "second.txt")], total=1)

        assert first.get_dir(0)[0][0]["FileName"] == "first.txt"
        assert second.get_dir(0)[0][0]["FileName"] == "second.txt"
        tables = {
            row["name"]
            for row in Database().query(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert first.table_name != second.table_name
        assert first.table_name in tables
        assert second.table_name in tables
        assert "first" not in first.table_name

    def test_shared_cache_migrates_to_first_account_only(self, tmp_db):
        Database().execute(
            "INSERT INTO dir_cache"
            " (dir_id, files, total, all_loaded, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("0", json.dumps([_file(1)]), 1, 1, "2024-01-01T00:00:00+00:00"),
        )

        default = FileListDB()
        first = FileListDB("first@example.com")
        second = FileListDB("second@example.com")

        assert default.get_dir(0) == (None, 0, False)
        assert first.get_dir(0)[0][0]["FileId"] == 1
        assert second.get_dir(0) == (None, 0, False)
        assert Database().query_one("SELECT * FROM dir_cache") is None

    def test_cache_hit_refreshes_lru_order(self, tmp_db, monkeypatch):
        import src.app.common.file_list_db as fldb_mod

        monkeypatch.setattr(fldb_mod, "_CACHE_MAX_ENTRIES", 2)
        db = FileListDB()
        db._cache.clear()
        db.save_dir(1, [_file(1)])
        db.save_dir(2, [_file(2)])
        db.get_dir(1)
        db.save_dir(3, [_file(3)])

        assert list(db._cache) == ["1", "3"]

    def test_is_stale(self, tmp_db):
        from datetime import datetime, timedelta, timezone

        db = FileListDB()
        # 无缓存视为过期
        assert db.is_stale(0) is True

        db.save_dir(0, [_file(1)], total=1)
        assert db.is_stale(0) is False

        # 手动改旧 updated_at 后视为过期
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        Database().execute(
            f"UPDATE {db.table_name} SET updated_at = ? WHERE dir_id = ?",
            (old, "0"),
        )
        assert db.is_stale(0) is True

    def test_dirty_marks(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1)], total=1)
        assert db.is_dirty(0) is False

        db.mark_dirty(0)
        assert db.is_dirty(0) is True
        # 保存后清除脏标记
        db.save_dir(0, [_file(2)], total=1)
        assert db.is_dirty(0) is False

    def test_mark_all_dirty(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1)])
        db.save_dir(1, [_file(2)])
        db.mark_all_dirty()
        assert db.is_dirty(0) is True
        assert db.is_dirty(1) is True

    def test_update_file_add(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1)], total=1)
        db.update_file_in_dir(0, 2, new_info=_file(2))
        files, total, _ = db.get_dir(0)
        assert total == 2
        assert [f["FileId"] for f in files] == [1, 2]

    def test_update_file_replace(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1, "old.txt")], total=1)
        db.update_file_in_dir(0, 1, new_info=_file(1, "new.txt"))
        files, total, _ = db.get_dir(0)
        assert total == 1
        assert files[0]["FileName"] == "new.txt"

    def test_update_file_remove(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1), _file(2)], total=2)
        db.update_file_in_dir(0, 1, remove=True)
        files, total, _ = db.get_dir(0)
        assert total == 1
        assert [f["FileId"] for f in files] == [2]

    def test_update_file_missing_dir(self, tmp_db):
        db = FileListDB()
        # 目录不存在时静默返回
        db.update_file_in_dir(999, 1, new_info=_file(1))
        assert db.get_dir(999) == (None, 0, False)

    def test_delete_dir(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1)])
        db.save_dir(1, [_file(2)])
        db.delete_dir(0)
        assert db.get_dir(0) == (None, 0, False)
        assert db.get_dir(1) != (None, 0, False)

    def test_delete_db_and_stats(self, tmp_db):
        db = FileListDB()
        db.save_dir(0, [_file(1), _file(2)])
        db.save_dir(1, [_file(3)])
        assert db.get_stats() == (2, 3)

        db.delete_db()
        assert db.get_stats() == (0, 0)
        assert db.get_dir(0) == (None, 0, False)

    def test_legacy_json_migration(self, tmp_db, tmp_path):
        """旧版 file_list_db.json 自动迁移到 SQLite。"""
        import src.app.common.file_list_db as fldb_mod

        fldb_mod.FILE_DB_PATH = tmp_path / "123pan" / "file_list_db.json"
        fldb_mod.FILE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        legacy = {
            "version": 2,
            "dirs": {
                "0": {
                    "files": [_file(1)],
                    "total": 1,
                    "all_loaded": True,
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            },
        }
        with open(fldb_mod.FILE_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(legacy, f)

        # 强制重建 FileListDB 单例触发迁移
        fldb_mod.FileListDB._instance = None
        db = FileListDB("legacy@example.com")

        files, total, all_loaded = db.get_dir(0)
        assert total == 1
        assert all_loaded is True
        assert files[0]["FileId"] == 1
        # 旧 JSON 已改名备份
        assert not fldb_mod.FILE_DB_PATH.exists()
        assert fldb_mod.FILE_DB_PATH.with_suffix(".json.bak").exists()
