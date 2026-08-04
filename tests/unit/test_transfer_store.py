"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from src.app.common.transfer_store import (
    STATUS_QUEUED,
    STATUS_RUNNING,
    TransferStore,
)


class TestTransferStoreActiveTasks:
    def test_add_and_get(self, tmp_db):
        store = TransferStore()
        tid = store.add_task(
            "upload", "a.txt", 100, priority=2, status=STATUS_QUEUED,
            local_path="/tmp/a", target_dir_id=0,
        )
        assert tid > 0

        tasks = store.get_active_tasks("upload")
        assert len(tasks) == 1
        assert tasks[0]["id"] == tid
        assert tasks[0]["file_name"] == "a.txt"
        assert tasks[0]["file_size"] == 100
        assert tasks[0]["priority"] == 2
        assert tasks[0]["status"] == STATUS_QUEUED

    def test_update_task(self, tmp_db):
        store = TransferStore()
        tid = store.add_task("download", "b.txt", 50, status=STATUS_QUEUED)
        store.update_task(tid, status=STATUS_RUNNING, progress=30)
        row = store.get_active_tasks("download")[0]
        assert row["status"] == STATUS_RUNNING
        assert row["progress"] == 30

    def test_update_no_fields(self, tmp_db):
        store = TransferStore()
        tid = store.add_task("upload", "c.txt", 10)
        # 不应抛异常
        store.update_task(tid)
        row = store.get_active_tasks("upload")[0]
        assert row["file_name"] == "c.txt"

    def test_remove_task(self, tmp_db):
        store = TransferStore()
        tid = store.add_task("upload", "d.txt", 10)
        store.remove_task(tid)
        assert store.get_active_tasks("upload") == []

    def test_remove_task_none(self, tmp_db):
        store = TransferStore()
        store.remove_task(None)  # 不应抛异常

    def test_clear_active_tasks(self, tmp_db):
        store = TransferStore()
        store.add_task("upload", "a.txt", 10)
        store.add_task("download", "b.txt", 20)
        store.clear_active_tasks("upload")
        assert store.get_active_tasks("upload") == []
        assert len(store.get_active_tasks("download")) == 1
        store.clear_active_tasks()
        assert store.get_active_tasks() == []


class TestTransferStoreHistory:
    def test_add_and_get_history(self, tmp_db):
        store = TransferStore()
        store.add_history("upload", "a.txt", 100, "已完成")
        store.add_history("download", "b.txt", 200, "失败")

        rows = store.get_history()
        assert len(rows) == 2
        # 最新在前
        assert rows[0]["file_name"] == "b.txt"
        assert rows[1]["file_name"] == "a.txt"
        assert rows[0]["status"] == "失败"
        assert rows[1]["file_size"] == 100

    def test_history_limit(self, tmp_db):
        store = TransferStore()
        for i in range(10):
            store.add_history("upload", f"f{i}.txt", i, "已完成")
        rows = store.get_history(limit=3)
        assert len(rows) == 3
        assert rows[0]["file_name"] == "f9.txt"

    def test_clear_history(self, tmp_db):
        store = TransferStore()
        store.add_history("upload", "a.txt", 1, "已完成")
        store.clear_history()
        assert store.get_history() == []
