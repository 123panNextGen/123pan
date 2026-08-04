"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock

from src.app.api.model import ApiCode, ApiReturnModel
from src.app.service.file_service import FileService
from src.app.tasks.file_tasks import MoveFileTask
from src.app.tasks.signals import _OpFinishedSignals


class TestFileServiceMove:
    def _make(self):
        session = MagicMock()
        svc = FileService(session)
        return svc, session

    def test_move_success(self, tmp_db):
        svc, session = self._make()
        session.mod_pid.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg=""
        )
        ok, msg = svc.move_files([1, 2], 99)
        assert ok is True
        assert msg == ""
        session.mod_pid.assert_called_once_with([1, 2], 99)

    def test_move_empty_list(self, tmp_db):
        svc, _ = self._make()
        ok, msg = svc.move_files([], 99)
        assert ok is False
        assert "列表为空" in msg

    def test_move_failure(self, tmp_db):
        svc, session = self._make()
        session.mod_pid.return_value = ApiReturnModel(
            code=403, api_code=403, api_code_enum=ApiCode.fail, msg="无权限"
        )
        ok, msg = svc.move_files([1], 99)
        assert ok is False
        assert "无权限" in msg


class TestMoveFileTask:
    def test_success(self):
        pan = MagicMock()
        pan.move_file.return_value = (True, "")
        fi = MagicMock()
        fi._reload_dir_data.return_value = ([{"FileId": 1}], [])
        results = []

        task = MoveFileTask(
            pan, [(1, "a.txt"), (2, "b.txt")], 99, 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        assert len(results) == 1
        success, name, new_name, error, items, folders = results[0]
        assert success is True
        assert error == ""
        assert items == [{"FileId": 1}]
        pan.move_file.assert_called_once_with([1, 2], 99)

    def test_failure(self):
        pan = MagicMock()
        pan.move_file.return_value = (False, "目标目录不存在")
        fi = MagicMock()
        results = []

        task = MoveFileTask(
            pan, [(1, "a.txt")], 99, 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        success, _, _, error, items, folders = results[0]
        assert success is False
        assert "目标目录不存在" in error
        fi._reload_dir_data.assert_not_called()

    def test_exception(self):
        pan = MagicMock()
        pan.move_file.side_effect = RuntimeError("boom")
        fi = MagicMock()
        results = []

        task = MoveFileTask(
            pan, [(1, "a.txt")], 99, 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        success, _, _, error, _, _ = results[0]
        assert success is False
        assert "boom" in error
