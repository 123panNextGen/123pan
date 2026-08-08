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
from src.app.common.api import Pan123
from src.app.service.file_service import FileService
from src.app.tasks.file_tasks import CopyFileTask, MoveFileTask
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


class TestFileServiceCopy:
    def _make(self):
        session = MagicMock()
        svc = FileService(session)
        return svc, session

    def test_copy_success_fallback_filelist(self, tmp_db):
        """无源目录信息时降级, fileList 仅携带 FileId。"""
        svc, session = self._make()
        session.copy_files_async.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="", data=1475675
        )
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="",
            data={"status": 2, "failMsg": ""},
        )
        ok, msg = svc.copy_files([1, 2], 99)
        assert ok is True
        assert msg == ""
        sent_list = session.copy_files_async.call_args[0][0]
        assert sent_list == [{"FileId": 1}, {"FileId": 2}]
        session.copy_file_task.assert_called_once_with(1475675)

    def test_copy_success_string_taskid(self, tmp_db):
        """任务 ID 为字符串时透传，不做 int() 强转。"""
        svc, session = self._make()
        session.copy_files_async.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="", data="abc123"
        )
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="",
            data={"status": 2, "failMsg": ""},
        )
        ok, msg = svc.copy_files([1], 99)
        assert ok is True
        assert msg == ""
        session.copy_file_task.assert_called_once_with("abc123")

    def test_copy_success_with_source_list(self, tmp_db, mocker):
        """有源目录信息时 fileList 使用完整文件对象并补 DriveId。"""
        svc, session = self._make()
        svc.get_dir_by_id = mocker.MagicMock(
            return_value=(0, [{"FileId": 1, "FileName": "a.txt", "Type": 0, "Size": 100}], 1, True, 1)
        )
        session.copy_files_async.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="", data=9
        )
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="",
            data={"status": 2, "failMsg": ""},
        )
        ok, msg = svc.copy_files([1], 99, source_parent_id=5)
        assert ok is True
        sent_list = session.copy_files_async.call_args[0][0]
        assert sent_list == [
            {"FileId": 1, "FileName": "a.txt", "Type": 0, "Size": 100, "DriveId": 0}
        ]
        svc.get_dir_by_id.assert_called_once()

    def test_copy_partial_source_list(self, tmp_db, mocker):
        """源目录列表不完整时，缺失项降级为仅 FileId，不静默丢文件。"""
        svc, session = self._make()
        svc.get_dir_by_id = mocker.MagicMock(
            return_value=(0, [{"FileId": 1, "FileName": "a.txt", "Type": 0}], 1, True, 1)
        )
        session.copy_files_async.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="", data=1
        )
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="",
            data={"status": 2, "failMsg": ""},
        )
        ok, msg = svc.copy_files([1, 2], 99, source_parent_id=5)
        assert ok is True
        sent_list = session.copy_files_async.call_args[0][0]
        assert sent_list == [
            {"FileId": 1, "FileName": "a.txt", "Type": 0, "DriveId": 0},
            {"FileId": 2},
        ]

    def test_copy_empty_list(self, tmp_db):
        svc, _ = self._make()
        ok, msg = svc.copy_files([], 99)
        assert ok is False
        assert "列表为空" in msg

    def test_copy_async_failure(self, tmp_db):
        svc, session = self._make()
        session.copy_files_async.return_value = ApiReturnModel(
            code=5066, api_code=5066, api_code_enum=ApiCode.fail, msg="文件不存在"
        )
        ok, msg = svc.copy_files([1], 99)
        assert ok is False
        assert "文件不存在" in msg
        session.copy_file_task.assert_not_called()

    def test_copy_task_failed_status(self, tmp_db):
        svc, session = self._make()
        session.copy_files_async.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="", data=1
        )
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="",
            data={"status": 3, "failMsg": "复制失败: 目标目录不存在"},
        )
        ok, msg = svc.copy_files([1], 99)
        assert ok is False
        assert "目标目录不存在" in msg

    def test_poll_copy_task_no_status_means_success(self, tmp_db):
        svc, session = self._make()
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="", data={}
        )
        ok, msg = svc._poll_copy_task(1, max_retries=2, interval=0.01)
        assert ok is True
        assert session.copy_file_task.call_count == 1

    def test_poll_copy_task_timeout(self, tmp_db):
        svc, session = self._make()
        session.copy_file_task.return_value = ApiReturnModel(
            code=0, api_code=200, api_code_enum=ApiCode.success, msg="",
            data={"status": 1, "failMsg": ""},
        )
        ok, msg = svc._poll_copy_task(1, max_retries=3, interval=0.01)
        assert ok is False
        assert "超时" in msg
        assert session.copy_file_task.call_count == 3


class TestCopyFileTask:
    def test_success(self):
        pan = MagicMock()
        pan.copy_file.return_value = (True, "")
        fi = MagicMock()
        fi._reload_dir_data.return_value = ([{"FileId": 1}], [])
        results = []

        task = CopyFileTask(
            pan, [(1, "a.txt"), (2, "b.txt")], 99, 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        assert len(results) == 1
        success, name, new_name, error, items, folders = results[0]
        assert success is True
        assert error == ""
        assert items == [{"FileId": 1}]
        pan.copy_file.assert_called_once_with([1, 2], 99, source_parent_id=0)

    def test_failure(self):
        pan = MagicMock()
        pan.copy_file.return_value = (False, "目标目录不存在")
        fi = MagicMock()
        results = []

        task = CopyFileTask(
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
        pan.copy_file.side_effect = RuntimeError("boom")
        fi = MagicMock()
        results = []

        task = CopyFileTask(
            pan, [(1, "a.txt")], 99, 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        success, _, _, error, _, _ = results[0]
        assert success is False
        assert "boom" in error

    def test_multi_targets_all_success(self):
        pan = MagicMock()
        pan.copy_file.return_value = (True, "")
        fi = MagicMock()
        fi._reload_dir_data.return_value = ([{"FileId": 1}], [])
        results = []

        task = CopyFileTask(
            pan, [(1, "a.txt")], [88, 99], 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        assert len(results) == 1
        success, name, new_name, error, items, folders = results[0]
        assert success is True
        assert error == ""
        assert items == [{"FileId": 1}]
        assert pan.copy_file.call_count == 2
        pan.copy_file.assert_any_call([1], 88, source_parent_id=0)
        pan.copy_file.assert_any_call([1], 99, source_parent_id=0)
        fi._reload_dir_data.assert_called_once_with(0)

    def test_multi_targets_partial_failure(self):
        pan = MagicMock()

        def _side_effect(fids, target, source_parent_id=None):
            return (True, "") if target == 88 else (False, "目标目录不存在")

        pan.copy_file.side_effect = _side_effect
        fi = MagicMock()
        fi._reload_dir_data.return_value = ([{"FileId": 1}], [])
        results = []

        task = CopyFileTask(
            pan, [(1, "a.txt")], [88, 99], 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        assert len(results) == 1
        success, _, _, error, items, folders = results[0]
        # 部分成功：success 仍为 True，错误信息带回失败目录明细
        assert success is True
        assert "目录#99" in error
        assert "目标目录不存在" in error
        assert items == [{"FileId": 1}]
        fi._reload_dir_data.assert_called_once_with(0)

    def test_multi_targets_all_failed(self):
        pan = MagicMock()
        pan.copy_file.return_value = (False, "复制超时")
        fi = MagicMock()
        results = []

        task = CopyFileTask(
            pan, [(1, "a.txt")], [88, 99], 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        success, _, _, error, _, _ = results[0]
        assert success is False
        assert "目录#88" in error
        assert "目录#99" in error
        fi._reload_dir_data.assert_not_called()

    def test_multi_targets_dedupe(self):
        pan = MagicMock()
        pan.copy_file.return_value = (True, "")
        fi = MagicMock()
        fi._reload_dir_data.return_value = ([], [])
        results = []

        task = CopyFileTask(
            pan, [(1, "a.txt")], [99, 99], 0, _OpFinishedSignals(), fi
        )
        task.signals.finished.connect(lambda *args: results.append(args))
        task.run()

        assert pan.copy_file.call_count == 1
        pan.copy_file.assert_called_once_with([1], 99, source_parent_id=0)


class TestPan123CopyFile:
    def test_copy_file_forwards_to_service(self):
        """门面 copy_file 转发到 FileService.copy_files（含 source_parent_id）。"""
        pan = Pan123.__new__(Pan123)  # 不触发真实 NetSession 初始化
        pan._file = MagicMock()
        pan.copy_file([1, 2], 99, source_parent_id=0)
        pan._file.copy_files.assert_called_once_with([1, 2], 99, 0)

    def test_copy_file_default_source(self):
        """未传 source_parent_id 时按 None 转发。"""
        pan = Pan123.__new__(Pan123)
        pan._file = MagicMock()
        pan.copy_file([1], 99)
        pan._file.copy_files.assert_called_once_with([1], 99, None)
