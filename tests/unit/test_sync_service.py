"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from types import SimpleNamespace

from src.app.service.sync_service import SyncService


class _DummySession:
    """最小可补丁的 session 替身。"""

    def trash_file(self, *args, **kwargs):
        return SimpleNamespace(code=0)


def _make_svc():
    return SyncService(_DummySession())


def _local_root(tmp_path):
    """独立于 tmp_db 数据库目录的本地同步根目录。"""
    root = tmp_path / "local"
    root.mkdir(exist_ok=True)
    return root


def _make_job(**overrides):
    job = {
        "id": 1,
        "name": "test_job",
        "local_path": "/tmp/nonexistent",
        "remote_dir_id": 0,
        "remote_dir_name": "",
        "direction": "upload",
        "interval_seconds": 0,
        "enabled": 1,
        "delete_remote": 0,
    }
    job.update(overrides)
    return job


class TestBuildLocalIndex:
    def test_index_files_and_dirs(self, tmp_path):
        root = _local_root(tmp_path)
        (root / "sub").mkdir()
        (root / "a.txt").write_bytes(b"hello")
        (root / "sub" / "b.bin").write_bytes(b"12345")
        svc = _make_svc()
        index = svc.build_local_index(str(root))

        assert index["a.txt"]["is_dir"] is False
        assert index["a.txt"]["size"] == 5
        assert index["sub"]["is_dir"] is True
        assert index["sub/b.bin"]["size"] == 5
        assert index["sub/b.bin"]["is_dir"] is False

    def test_nonexistent_dir(self, tmp_path):
        svc = _make_svc()
        assert svc.build_local_index(str(tmp_path / "nope")) == {}

    def test_abs_path_resolution(self, tmp_path):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"x")
        svc = _make_svc()
        index = svc.build_local_index(str(root))
        assert os.path.isabs(index["a.txt"]["abs"])


class TestComputeChanges:
    def test_first_sync_uploads_all_new(self, tmp_db, tmp_path):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"x")
        svc = _make_svc()
        local = svc.build_local_index(str(root))
        job = _make_job(local_path=str(root))
        uploads, dirs, deletes = svc.compute_changes(job, local, {})
        assert len(uploads) == 1
        rel, _abs, parent, is_new = uploads[0]
        assert rel == "a.txt"
        assert parent == ""
        assert is_new is True
        assert dirs == []
        assert deletes == []

    def test_cloud_size_match_marks_synced(self, tmp_db, tmp_path):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"xxxxx")
        svc = _make_svc()
        job = _make_job(local_path=str(root))
        local = svc.build_local_index(str(root))
        remote = {"a.txt": {"FileId": 1, "Type": 0, "Size": 5}}
        uploads, _, _ = svc.compute_changes(job, local, remote)
        assert uploads == []
        # 指纹已记录，再次对比仍不上传
        uploads, _, _ = svc.compute_changes(job, local, remote)
        assert uploads == []

    def test_size_changed_triggers_overwrite(self, tmp_db, tmp_path):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"x")
        svc = _make_svc()
        job = _make_job(local_path=str(root))
        local = svc.build_local_index(str(root))
        remote = {"a.txt": {"FileId": 1, "Type": 0, "Size": 999}}
        uploads, _, _ = svc.compute_changes(job, local, remote)
        assert len(uploads) == 1
        assert uploads[0][3] is False  # is_new=False → 覆盖上传

    def test_same_size_mtime_change_uploaded(self, tmp_db, tmp_path):
        root = _local_root(tmp_path)
        f = root / "a.txt"
        f.write_bytes(b"xxxxx")
        svc = _make_svc()
        job = _make_job(local_path=str(root))
        local = svc.build_local_index(str(root))
        remote = {"a.txt": {"FileId": 1, "Type": 0, "Size": 5}}
        # 首次：云端大小一致，记录指纹不上传
        uploads, _, _ = svc.compute_changes(job, local, remote)
        assert uploads == []
        # 同尺寸但 mtime 变化（内容可能已改）→ 上传
        old = f.stat().st_mtime
        os.utime(f, (old + 100, old + 100))
        local2 = svc.build_local_index(str(root))
        uploads, _, _ = svc.compute_changes(job, local2, remote)
        assert len(uploads) == 1

    def test_delete_remote_lists_missing(self, tmp_db, tmp_path):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"x")
        svc = _make_svc()
        local = svc.build_local_index(str(root))
        remote = {
            "a.txt": {"FileId": 1, "Type": 0, "Size": 1},
            "gone.txt": {"FileId": 2, "Type": 0, "Size": 5},
            "gone_dir": {"FileId": 3, "Type": 1, "Size": 0},
        }
        job = _make_job(local_path=str(root), delete_remote=1)
        _, _, deletes = svc.compute_changes(job, local, remote)
        assert set(deletes) == {"gone.txt", "gone_dir"}

    def test_dir_creation_plan(self, tmp_db, tmp_path):
        root = _local_root(tmp_path)
        (root / "sub").mkdir()
        (root / "sub" / "f.txt").write_bytes(b"x")
        svc = _make_svc()
        local = svc.build_local_index(str(root))
        job = _make_job(local_path=str(root))
        uploads, dirs, _ = svc.compute_changes(job, local, {})
        assert ("sub", "") in dirs
        rels = [u[0] for u in uploads]
        assert "sub/f.txt" in rels
        # 子目录文件的上传父目录为 sub
        parent_of_sub = next(u[2] for u in uploads if u[0] == "sub/f.txt")
        assert parent_of_sub == "sub"


class TestRunSync:
    def test_run_sync_uploads_new_file(self, tmp_db, tmp_path, mocker):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"hello")
        svc = _make_svc()
        job = _make_job(local_path=str(root))

        # 云端为空
        mocker.patch.object(svc._file, "get_dir_by_id", return_value=(0, [], 0, True, 1))
        mocker.patch.object(svc._upload, "up_load", return_value=99)
        mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        ok, stats = svc.run_sync(job)
        assert ok is True
        assert stats["added"] == 1
        assert stats["failed"] == 0
        # 上传后记录指纹
        fps = svc._store.get_fingerprints(1)
        assert "a.txt" in fps
        # up_load 使用新文件策略（duplicate=0）
        _, kwargs = svc._upload.up_load.call_args
        assert kwargs.get("dup_choice") == 0

    def test_run_sync_second_pass_noop(self, tmp_db, tmp_path, mocker):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"hello")
        svc = _make_svc()
        job = _make_job(local_path=str(root))

        mocker.patch.object(svc._file, "get_dir_by_id", return_value=(0, [], 0, True, 1))
        mocker.patch.object(svc._upload, "up_load", return_value=99)
        mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        ok, stats = svc.run_sync(job)
        assert stats["added"] == 1

        # 第二次运行：云端出现相同文件，且指纹已记录 → 无操作
        mocker.patch.object(
            svc._file, "get_dir_by_id",
            return_value=(
                0,
                [{"FileId": 99, "FileName": "a.txt", "Type": 0, "Size": 5}],
                1, True, 1,
            ),
        )
        svc._upload.up_load.reset_mock()
        ok, stats = svc.run_sync(job)
        assert ok is True
        assert stats["added"] == 0
        assert stats["updated"] == 0
        svc._upload.up_load.assert_not_called()

    def test_run_sync_creates_remote_dir(self, tmp_db, tmp_path, mocker):
        root = _local_root(tmp_path)
        (root / "sub").mkdir()
        (root / "sub" / "f.txt").write_bytes(b"hello")
        svc = _make_svc()
        job = _make_job(local_path=str(root))

        mocker.patch.object(svc._file, "get_dir_by_id", return_value=(0, [], 0, True, 1))
        mocker.patch.object(svc._file, "create_folder", return_value=(555, ""))
        mocker.patch.object(svc._upload, "up_load", return_value=99)
        mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        ok, stats = svc.run_sync(job)
        assert ok is True
        assert stats["added"] == 1
        # 先建目录再上传，上传父目录为新建的 555
        svc._file.create_folder.assert_called_once_with("sub", 0)
        upload_parent = svc._upload.up_load.call_args.args[1]
        assert upload_parent == 555

    def test_run_sync_deletes_remote(self, tmp_db, tmp_path, mocker):
        root = _local_root(tmp_path)
        (root / "keep.txt").write_bytes(b"x")
        svc = _make_svc()
        job = _make_job(local_path=str(root), delete_remote=1)

        remote_items = [
            {"FileId": 1, "FileName": "keep.txt", "Type": 0, "Size": 1},
            {"FileId": 2, "FileName": "gone.txt", "Type": 0, "Size": 5},
        ]
        mocker.patch.object(
            svc._file, "get_dir_by_id",
            return_value=(0, remote_items, 2, True, 1),
        )
        mocker.patch.object(svc._upload, "up_load", return_value=99)
        trash = mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        ok, stats = svc.run_sync(job)
        assert ok is True
        assert stats["deleted"] == 1
        # 删除的是 gone.txt
        deleted_payload = trash.call_args.args[0]
        assert deleted_payload["FileName"] == "gone.txt"

    def test_run_sync_cancel(self, tmp_db, tmp_path, mocker):
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"hello")
        svc = _make_svc()
        job = _make_job(local_path=str(root))

        mocker.patch.object(svc._file, "get_dir_by_id", return_value=(0, [], 0, True, 1))
        mocker.patch.object(svc._upload, "up_load", return_value=99)
        mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        cancel = SimpleNamespace(is_cancelled=True)
        ok, stats = svc.run_sync(job, cancel=cancel)
        assert ok is False

    def test_run_sync_remote_failure_aborts(self, tmp_db, tmp_path, mocker):
        """云端列表获取失败时必须中止，防止误传/误删。"""
        root = _local_root(tmp_path)
        (root / "a.txt").write_bytes(b"hello")
        svc = _make_svc()
        job = _make_job(local_path=str(root), delete_remote=1)

        # get_dir_by_id 返回失败码（如 token 过期）
        mocker.patch.object(
            svc._file, "get_dir_by_id", return_value=(2, [], 0, False, 0)
        )
        upload = mocker.patch.object(svc._upload, "up_load", return_value=99)
        trash = mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        ok, stats = svc.run_sync(job)
        assert ok is False
        upload.assert_not_called()
        trash.assert_not_called()

    def test_run_sync_invalid_local_dir_aborts(self, tmp_db, tmp_path, mocker):
        """本地目录不存在时中止，避免 delete_remote 误删云端。"""
        svc = _make_svc()
        job = _make_job(local_path=str(tmp_path / "missing"), delete_remote=1)

        mocker.patch.object(svc._file, "get_dir_by_id", return_value=(0, [], 0, True, 1))
        upload = mocker.patch.object(svc._upload, "up_load", return_value=99)
        trash = mocker.patch.object(
            svc._session, "trash_file",
            return_value=SimpleNamespace(code=0),
        )

        ok, stats = svc.run_sync(job)
        assert ok is False
        upload.assert_not_called()
        trash.assert_not_called()
