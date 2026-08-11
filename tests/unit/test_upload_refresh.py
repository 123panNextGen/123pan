"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.tasks.transfer_tasks import UploadTask
from src.app.view.transfer_interface import TransferInterface

_app = QApplication.instance() or QApplication([])


class TestUploadDirInvalidation:
    """上传完成后目录缓存失效与列表刷新。"""

    def test_marks_target_dir_dirty(self, tmp_db):
        """上传完成后目标目录缓存被标记为脏。"""
        ti = TransferInterface()
        ti.pan = MagicMock()
        task = UploadTask("a.txt", 10, "/tmp/a.txt", 42)
        ti._invalidate_upload_dir(task)
        ti.pan.mark_dir_dirty.assert_called_once_with(42)

    def test_refreshes_current_dir_when_viewing_target(self, tmp_db):
        """当前正浏览上传目标目录时，强制刷新文件列表。"""
        ti = TransferInterface()
        ti.pan = MagicMock()

        # 模拟 MainWindow：file_interface.current_dir_id 与目标一致
        mw = MagicMock()
        mw.file_interface.current_dir_id = 42
        mw.file_interface._loadCurrentList = MagicMock()
        with patch.object(ti, "window", return_value=mw):
            ti._invalidate_upload_dir(UploadTask("a.txt", 10, "/tmp/a.txt", 42))

        ti.pan.mark_dir_dirty.assert_called_once_with(42)
        mw.file_interface._loadCurrentList.assert_called_once_with(
            force_refresh=True
        )

    def test_no_refresh_when_viewing_other_dir(self, tmp_db):
        """浏览其他目录时只标记脏，不强制刷新当前列表。"""
        ti = TransferInterface()
        ti.pan = MagicMock()

        mw = MagicMock()
        mw.file_interface.current_dir_id = 7  # 当前浏览目录 != 目标
        mw.file_interface._loadCurrentList = MagicMock()
        with patch.object(ti, "window", return_value=mw):
            ti._invalidate_upload_dir(UploadTask("a.txt", 10, "/tmp/a.txt", 42))

        ti.pan.mark_dir_dirty.assert_called_once_with(42)
        mw.file_interface._loadCurrentList.assert_not_called()

    def test_no_pan_does_nothing(self, tmp_db):
        """pan 未设置时不崩溃。"""
        ti = TransferInterface()
        ti.pan = None
        ti._invalidate_upload_dir(UploadTask("a.txt", 10, "/tmp/a.txt", 42))


class TestFileServiceMarkDirDirty:
    """FileService.mark_dir_dirty 标记目录缓存为脏。"""

    def test_mark_dirty(self, tmp_db):
        from unittest.mock import MagicMock

        from src.app.common.file_list_db import FileListDB
        from src.app.service.file_service import FileService

        session = MagicMock()
        svc = FileService(session)
        svc.mark_dir_dirty(99)
        assert FileListDB().is_dirty(99) is True
        # 其他目录不受影响
        assert FileListDB().is_dirty(100) is False

