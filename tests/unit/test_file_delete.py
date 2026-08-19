"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

删除流程回归测试：
- DeleteFileTask 必须校验删除 API 的真实结果（此前忽略返回值，删除失败也报成功）
- 删除成功后必须强制刷新目录（此前走缓存，删除的文件仍显示 → “无法删除文件”）
- pan.delete_file 必须透传 parent_file_id，使目录缓存失效
"""

from src.app.tasks.file_tasks import (
    BatchDeleteTask,
    DeleteFileTask,
    LoadFolderListTask,
    RestoreTrashTask,
)
from src.app.tasks.signals import _FolderListSignals, _OpFinishedSignals, _TrashOpSignals


class _MockPan:
    """模拟 Pan123：内存列表 + delete_file。"""

    def __init__(self, files, delete_result=(True, "")):
        self.list = list(files)
        self.file_page = 0
        self.total = 0
        self.all_file = False
        self._delete_result = delete_result
        self.delete_calls = []  # (index, kwargs)

    def get_dir_by_id(self, dir_id, save=False, all=False, limit=100,
                      force_refresh=False):
        # 返回与内存列表一致的数据
        return 0, self.list

    def delete_file(self, file, by_num=True, operation=True, parent_file_id=None):
        self.delete_calls.append((file, {
            "by_num": by_num,
            "operation": operation,
            "parent_file_id": parent_file_id,
        }))
        return self._delete_result


class _MockInterface:
    """模拟 FileInterface：记录 _reload_dir_data 的 force_refresh 参数。"""

    def __init__(self):
        self.reload_calls = []

    def _reload_dir_data(self, dir_id, force_refresh=False):
        self.reload_calls.append((dir_id, force_refresh))
        return [{"FileId": 2, "FileName": "keep.txt", "Type": 0}], []


def _run(task, signals):
    results = {}

    def on_finished(success, name, new_name, error, items, folders):
        results.update(
            success=success, name=name, new_name=new_name,
            error=error, items=items, folders=folders,
        )

    signals.finished.connect(on_finished)
    task.run()
    return results


class TestDeleteFileTask:
    def test_success_refreshes_force(self):
        """删除成功后必须强制刷新目录，并透传 parent_file_id。"""
        pan = _MockPan([
            {"FileId": 1, "FileName": "a.txt", "Type": 0},
            {"FileId": 2, "FileName": "keep.txt", "Type": 0},
        ])
        fi = _MockInterface()
        signals = _OpFinishedSignals()
        task = DeleteFileTask(pan, 1, "a.txt", 10, signals, fi)
        result = _run(task, signals)

        assert result["success"] is True
        # 调用 delete_file 且透传 parent_file_id
        idx, kwargs = pan.delete_calls[0]
        assert kwargs["parent_file_id"] == 10
        # 删除后强制刷新
        assert fi.reload_calls == [(10, True)]

    def test_api_failure_reports_error(self):
        """删除 API 返回失败时必须上报错误，不得报成功。"""
        pan = _MockPan(
            [{"FileId": 1, "FileName": "a.txt", "Type": 0}],
            delete_result=(False, "文件不存在或已被删除"),
        )
        fi = _MockInterface()
        signals = _OpFinishedSignals()
        task = DeleteFileTask(pan, 1, "a.txt", 10, signals, fi)
        result = _run(task, signals)

        assert result["success"] is False
        assert "文件不存在或已被删除" in result["error"]
        # 失败时不刷新目录（界面保持原样）
        assert fi.reload_calls == []

    def test_not_found_reports_failure(self):
        """文件不在列表中且刷新后仍找不到 → 报失败。"""
        pan = _MockPan([{"FileId": 2, "FileName": "keep.txt", "Type": 0}])
        fi = _MockInterface()
        signals = _OpFinishedSignals()
        task = DeleteFileTask(pan, 99, "ghost.txt", 10, signals, fi)
        result = _run(task, signals)

        assert result["success"] is False
        assert pan.delete_calls == []
        # 找不到也会强制刷新一次目录
        assert fi.reload_calls == []


class TestBatchDeleteTask:
    def test_batch_checks_result_and_refreshes(self):
        """批量删除：部分失败要计数，成功则强制刷新。"""
        pan = _MockPan([
            {"FileId": 1, "FileName": "a.txt", "Type": 0},
            {"FileId": 2, "FileName": "b.txt", "Type": 0},
        ])
        fi = _MockInterface()
        signals = _OpFinishedSignals()

        # 第一个成功、第二个失败
        def fake_delete(file, by_num=True, operation=True, parent_file_id=None):
            pan.delete_calls.append((file, {
                "by_num": by_num, "operation": operation,
                "parent_file_id": parent_file_id,
            }))
            return (True, "") if file == 0 else (False, "删除失败")

        pan.delete_file = fake_delete

        task = BatchDeleteTask(pan, [(1, "a.txt"), (2, "b.txt")], 10, signals, fi)
        result = _run(task, signals)

        assert result["success"] is True
        assert "成功 1 个" in result["name"]
        assert "失败 1 个" in result["name"]
        assert result["error"] == "删除失败"
        # 每次删除都透传 parent_file_id
        assert all(kwargs["parent_file_id"] == 10 for _, kwargs in pan.delete_calls)
        # 完成后强制刷新
        assert fi.reload_calls == [(10, True)]


class TestBackgroundFileTasks:
    def test_folder_loader_does_not_mutate_pan_browse_state(self):
        """目录树后台加载必须不影响当前文件列表的分页状态。"""
        pan = _MockPan([])
        pan.file_page = 7
        pan.total = 42
        pan.all_file = True
        pan.get_dir_by_id = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("目录树加载不应调用有状态 Pan123.get_dir_by_id")
        )
        pan._file = type("FileService", (), {
            "get_dir_by_id": lambda _, *args, **kwargs: (
                0,
                [{"FileId": 1, "Type": 1}, {"FileId": 2, "Type": 0}],
                2,
                True,
                1,
            )
        })()
        signals = _FolderListSignals()
        result = {}
        signals.finished.connect(
            lambda dir_id, folders, error: result.update(
                dir_id=dir_id, folders=folders, error=error
            )
        )

        LoadFolderListTask(pan, 10, signals).run()

        assert result["dir_id"] == 10
        assert result["folders"] == [{"FileId": 1, "Type": 1}]
        assert result["error"] == ""
        assert (pan.file_page, pan.total, pan.all_file) == (7, 42, True)

    def test_restore_trash_reports_service_failure(self):
        """回收站恢复接口失败时不得误报成功。"""
        pan = _MockPan([])
        pan._file = type("FileService", (), {
            "delete_file": lambda *args, **kwargs: (False, "文件不存在")
        })()
        signals = _TrashOpSignals()
        result = {}
        signals.finished.connect(
            lambda success, message: result.update(success=success, message=message)
        )

        RestoreTrashTask(pan, [{"FileId": 1}], [{"FileId": 1}], signals).run()

        assert result == {"success": False, "message": "文件不存在"}
