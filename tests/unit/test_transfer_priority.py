"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.app.common.i18n import tr
from src.app.tasks.transfer_tasks import TransferTask, UploadTask
from src.app.view.transfer_interface import TransferInterface

_app = QApplication.instance() or QApplication([])


class TestPickNextPending:
    """等待队列优先级选择逻辑。"""

    def _make(self, tmp_db):
        return TransferInterface()

    def test_picks_highest_priority(self, tmp_db):
        ti = self._make(tmp_db)
        low = UploadTask("low.txt", 1, "/tmp/low", 0)
        low.priority = TransferTask.PRIORITY_LOW
        normal = UploadTask("normal.txt", 1, "/tmp/normal", 0)
        high = UploadTask("high.txt", 1, "/tmp/high", 0)
        high.priority = TransferTask.PRIORITY_HIGH

        assert ti._pick_next_pending([low, normal, high]) is high

    def test_fifo_on_tie(self, tmp_db):
        ti = self._make(tmp_db)
        a = UploadTask("a.txt", 1, "/tmp/a", 0)
        b = UploadTask("b.txt", 1, "/tmp/b", 0)
        c = UploadTask("c.txt", 1, "/tmp/c", 0)
        # 同优先级保持先入先出
        assert ti._pick_next_pending([a, b, c]) is a

    def test_empty_queue(self, tmp_db):
        ti = self._make(tmp_db)
        assert ti._pick_next_pending([]) is None

    def test_queue_slots_full_returns_none(self, tmp_db):
        ti = self._make(tmp_db)
        ti._pending_upload_queue = [UploadTask("x.txt", 1, "/tmp/x", 0)]
        ti._active_upload_count = ti._max_concurrent_uploads
        with patch.object(
            ti, "_TransferInterface__start_upload_thread"
        ) as mock_start:
            ti._TransferInterface__start_next_pending_upload()
        mock_start.assert_not_called()


class TestStartNextPending:
    """启动下一个排队任务时按优先级选择。"""

    def test_upload_starts_highest_priority(self, tmp_db):
        ti = TransferInterface()
        ti._pending_upload_queue = []
        low = UploadTask("low.txt", 1, "/tmp/low", 0)
        low.priority = TransferTask.PRIORITY_LOW
        high = UploadTask("high.txt", 1, "/tmp/high", 0)
        high.priority = TransferTask.PRIORITY_HIGH
        ti._pending_upload_queue = [low, high]
        ti._active_upload_count = 0

        with patch.object(
            ti, "_TransferInterface__start_upload_thread"
        ) as mock_start, patch.object(
            ti, "_TransferInterface__update_upload_table"
        ):
            ti._TransferInterface__start_next_pending_upload()

        mock_start.assert_called_once_with(high)
        assert high not in ti._pending_upload_queue
        assert low in ti._pending_upload_queue

    def test_queued_status_set_to_waiting(self, tmp_db):
        ti = TransferInterface()
        task = UploadTask("a.txt", 1, "/tmp/a", 0)
        task.status = tr("transfer.status_queued", "排队中")
        ti._pending_upload_queue = [task]
        ti._active_upload_count = 0

        with patch.object(
            ti, "_TransferInterface__start_upload_thread"
        ) as mock_start, patch.object(
            ti, "_TransferInterface__update_upload_table"
        ):
            ti._TransferInterface__start_next_pending_upload()

        assert task.status == tr("transfer.status_waiting", "等待中")
        mock_start.assert_called_once_with(task)
