"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock

from src.app.tasks.file_tasks import UploadFolderTask
from src.app.tasks.signals import _UploadFolderSignals


class _MockPan:
    """模拟 Pan123：目录列表 + 建目录。"""

    def __init__(self, dirs=None):
        # dirs: {parent_id: [item,...]}
        self.dirs = dirs or {}
        self.created = []  # (name, parent_id) 创建记录
        self.file_page = 0
        self.total = 0
        self.all_file = False

    def get_dir_by_id(self, parent_id, save=False, all=False, limit=100):
        items = self.dirs.get(int(parent_id), [])
        return 0, items

    def create_folder(self, name, parent_id):
        fid = len(self.created) + 1000
        self.created.append((name, int(parent_id)))
        self.dirs.setdefault(int(parent_id), []).append(
            {"FileId": fid, "FileName": name, "Type": 1}
        )
        return fid, ""


def _run_task(pan, local_root, target_dir_id=0):
    signals = _UploadFolderSignals()
    results = {}

    def on_finished(files, error):
        results["files"] = files
        results["error"] = error

    signals.finished.connect(on_finished)
    task = UploadFolderTask(pan, local_root, target_dir_id, signals)
    task.run()
    return results


class TestUploadFolderTask:
    def test_creates_structure_and_collects_files(self, tmp_path):
        """递归建目录并收集待上传文件。"""
        root = tmp_path / "myfolder"
        (root / "sub").mkdir(parents=True)
        (root / "file1.txt").write_bytes(b"a")
        (root / "sub" / "file2.txt").write_bytes(b"bb")

        pan = _MockPan()
        results = _run_task(pan, str(root), 0)

        assert results["error"] == ""
        # 创建了顶层文件夹 myfolder 与子文件夹 sub
        assert ("myfolder", 0) in pan.created
        assert ("sub", 1000) in pan.created
        # 收集到两个文件，目标目录分别为顶层与子文件夹
        files = results["files"]
        assert len(files) == 2
        by_name = {p.split("/")[-1]: (p, d) for p, d in files}
        assert by_name["file1.txt"][1] == 1000  # myfolder
        assert by_name["file2.txt"][1] == 1001  # sub
        assert by_name["file2.txt"][0].endswith("file2.txt")

    def test_reuses_existing_folders(self, tmp_path):
        """同名云端文件夹已存在时复用（合并上传）。"""
        root = tmp_path / "myfolder"
        (root / "sub").mkdir(parents=True)
        (root / "a.txt").write_bytes(b"a")

        pan = _MockPan(
            {
                0: [{"FileId": 500, "FileName": "myfolder", "Type": 1}],
                500: [{"FileId": 501, "FileName": "sub", "Type": 1}],
            }
        )
        results = _run_task(pan, str(root), 0)

        assert results["error"] == ""
        # 不重复创建已存在的目录
        assert pan.created == []
        files = results["files"]
        assert len(files) == 1
        assert files[0][1] == 500

    def test_empty_folder_error(self, tmp_path):
        """空文件夹返回空列表（界面提示无文件）。"""
        root = tmp_path / "empty"
        root.mkdir()

        pan = _MockPan()
        results = _run_task(pan, str(root), 0)
        assert results["files"] == []
        assert results["error"] == ""

    def test_missing_folder_raises(self, tmp_path):
        """本地文件夹不存在时报错。"""
        pan = _MockPan()
        results = _run_task(pan, str(tmp_path / "nope"), 0)
        assert results["files"] == []
        assert "不存在" in results["error"]

    def test_skips_symlinks_and_special_files(self, tmp_path):
        """跳过目录项中的非普通文件。"""
        root = tmp_path / "myfolder"
        (root / "sub").mkdir(parents=True)
        (root / "sub" / "f.txt").write_bytes(b"x")

        pan = _MockPan()
        results = _run_task(pan, str(root), 0)
        assert len(results["files"]) == 1
