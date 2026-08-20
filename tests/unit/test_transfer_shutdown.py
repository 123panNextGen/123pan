"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.tasks.transfer_tasks import DownloadThread, UploadThread
from src.app.view.transfer_interface import TransferInterface

_app = QApplication.instance() or QApplication([])


class TestShutdown:
    """应用退出时传输线程清理（避免 QThread 销毁警告）。"""

    def test_no_threads_noop(self, tmp_db):
        ti = TransferInterface()
        ti.shutdown()  # 不应抛异常
        assert ti.upload_threads == []
        assert ti.download_threads == []

    def test_cancels_and_waits_all_threads(self, tmp_db):
        ti = TransferInterface()
        up = MagicMock(spec=UploadThread)
        dl = MagicMock(spec=DownloadThread)
        up.isRunning.return_value = True
        dl.isRunning.return_value = True
        ti.upload_threads.append(up)
        ti.download_threads.append(dl)

        ti.shutdown()

        up.cancel.assert_called_once_with()
        dl.cancel.assert_called_once_with()
        up.wait.assert_called_once_with(15000)
        dl.wait.assert_called_once_with(15000)
        assert ti.upload_threads == []
        assert ti.download_threads == []

    def test_skips_wait_for_finished_thread(self, tmp_db):
        ti = TransferInterface()
        up = MagicMock(spec=UploadThread)
        up.isRunning.return_value = False
        ti.upload_threads.append(up)

        ti.shutdown()

        up.cancel.assert_called_once_with()
        up.wait.assert_not_called()
        assert ti.upload_threads == []
