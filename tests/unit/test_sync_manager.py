"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import pytest
from PySide6.QtCore import QCoreApplication

from src.app.tasks.sync_manager import SyncManager


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


class TestSyncManagerScheduler:
    def test_manual_job_not_scheduled(self, tmp_db, qapp, mocker):
        mgr = SyncManager()
        mgr._pan = object()  # 模拟已登录
        mgr.add_job(
            name="manual", local_path="/tmp/x", remote_dir_id=0,
            interval_seconds=0, enabled=True,
        )
        run = mocker.patch.object(mgr, "run_job")
        mgr._check_scheduled()
        run.assert_not_called()
        mgr.shutdown()

    def test_interval_job_without_last_run_triggers(self, tmp_db, qapp, mocker):
        mgr = SyncManager()
        mgr._pan = object()
        mgr.add_job(
            name="auto", local_path="/tmp/y", remote_dir_id=0,
            interval_seconds=60, enabled=True,
        )
        run = mocker.patch.object(mgr, "run_job")
        mgr._check_scheduled()
        run.assert_called_once()
        mgr.shutdown()

    def test_disabled_job_not_scheduled(self, tmp_db, qapp, mocker):
        mgr = SyncManager()
        mgr._pan = object()
        mgr.add_job(
            name="disabled", local_path="/tmp/y", remote_dir_id=0,
            interval_seconds=60, enabled=False,
        )
        run = mocker.patch.object(mgr, "run_job")
        mgr._check_scheduled()
        run.assert_not_called()
        mgr.shutdown()

    def test_running_job_not_retriggered(self, tmp_db, qapp, mocker):
        mgr = SyncManager()
        mgr._pan = object()

        class _FakeThread:
            def cancel(self):
                pass

            def isRunning(self):
                return False

        job_id = mgr.add_job(
            name="auto", local_path="/tmp/y", remote_dir_id=0,
            interval_seconds=60, enabled=True,
        )
        mgr._running[job_id] = _FakeThread()  # 已在运行
        run = mocker.patch.object(mgr, "run_job")
        mgr._check_scheduled()
        run.assert_not_called()
        mgr.shutdown()

    def test_interval_elapsed_triggers(self, tmp_db, qapp, mocker):
        from datetime import datetime, timedelta, timezone

        mgr = SyncManager()
        mgr._pan = object()
        job_id = mgr.add_job(
            name="auto", local_path="/tmp/y", remote_dir_id=0,
            interval_seconds=60, enabled=True,
        )
        # 2 分钟前运行过 → 间隔 60s 已到期
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        mgr._store.set_job_last_run(job_id)
        mgr._store._db.execute(
            "UPDATE sync_jobs SET last_run_at = ? WHERE id = ?", (old, job_id)
        )
        run = mocker.patch.object(mgr, "run_job")
        mgr._check_scheduled()
        run.assert_called_once()
        mgr.shutdown()

    def test_interval_not_elapsed_skips(self, tmp_db, qapp, mocker):
        from datetime import datetime, timedelta, timezone

        mgr = SyncManager()
        mgr._pan = object()
        job_id = mgr.add_job(
            name="auto", local_path="/tmp/y", remote_dir_id=0,
            interval_seconds=3600, enabled=True,
        )
        # 5 分钟前运行过 → 间隔 1h 未到期
        old = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        mgr._store._db.execute(
            "UPDATE sync_jobs SET last_run_at = ? WHERE id = ?", (old, job_id)
        )
        run = mocker.patch.object(mgr, "run_job")
        mgr._check_scheduled()
        run.assert_not_called()
        mgr.shutdown()

    def test_run_all_enabled_only(self, tmp_db, qapp, mocker):
        mgr = SyncManager()
        mgr._pan = object()
        mgr.add_job(
            name="a", local_path="/tmp/a", remote_dir_id=0,
            interval_seconds=0, enabled=True,
        )
        mgr.add_job(
            name="b", local_path="/tmp/b", remote_dir_id=0,
            interval_seconds=0, enabled=False,
        )
        run = mocker.patch.object(mgr, "run_job")
        mgr.run_all_enabled()
        # 仅启用任务被调度（2 个参数：手动也执行）
        assert run.call_count == 1
        mgr.shutdown()
