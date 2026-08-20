"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock

from src.app.service.upload_service import UploadService


class TestComputeFileMd5Progress:
    """MD5 校验进度回调。"""

    def test_progress_callback_reports_percent(self, tmp_path):
        """校验进度回调收到 0-100 的百分比序列。"""
        svc = UploadService(MagicMock())
        f = tmp_path / "f.bin"
        # 1MB 文件，确保回调多次
        f.write_bytes(b"x" * (1024 * 1024))

        percents = []
        md5 = svc.compute_file_md5(
            str(f), progress_callback=lambda p: percents.append(p)
        )
        assert md5  # 非空
        assert percents
        assert percents[0] >= 0
        assert percents[-1] == 100
        # 单调不减
        assert all(a <= b for a, b in zip(percents, percents[1:]))

    def test_md5_cancel_stops_reading(self, tmp_path):
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * (1024 * 1024 * 4))
        checks = []

        result = UploadService.compute_file_md5(
            str(f),
            progress_callback=lambda percent: checks.append(percent),
            cancel_check=lambda: bool(checks),
        )

        assert result is None
        assert checks

    def test_progress_callback_not_spammy(self, tmp_path):
        """同一百分比只回调一次（避免高频信号）。"""
        svc = UploadService(MagicMock())
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * (1024 * 1024))

        percents = []
        svc.compute_file_md5(str(f), progress_callback=lambda p: percents.append(p))
        # 百分比唯一（除 100 外不重复）
        assert len(percents) == len(set(percents))

    def test_no_callback_works(self, tmp_path):
        """无回调时正常计算。"""
        svc = UploadService(MagicMock())
        f = tmp_path / "f.bin"
        f.write_bytes(b"abc")
        md5 = svc.compute_file_md5(str(f))
        assert md5 == "900150983cd24fb0d6963f7d28e17f72"

    def test_up_load_passes_validation_callback(self, tmp_path):
        """up_load 将 validation_callback 传给 MD5 计算。"""
        svc = UploadService(MagicMock())
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * 100)

        # 构造 upload_request 返回 Reuse=True，走秒传路径不计算 MD5？
        # 这里改用 Reuse=False + 后续 mock，验证 callback 被传入 MD5 计算
        session = MagicMock()

        def _post(url, *args, **kwargs):
            url = str(url)
            if "upload_request" in url:
                return MagicMock(json=lambda: {
                    "code": 0,
                    "data": {
                        "Reuse": False,
                        "Bucket": "b", "StorageNode": "s", "Key": "k",
                        "UploadId": "u", "FileId": 1,
                    },
                })
            if "s3_repare_upload_parts_batch" in url:
                return MagicMock(json=lambda: {
                    "code": 0,
                    "data": {"presignedUrls": {"1": "http://cdn/1"}},
                })
            return MagicMock(json=lambda: {"code": 0})

        session.http.post.side_effect = _post
        session.transfer.put = MagicMock()
        svc2 = UploadService(session)

        validation_percents = []
        svc2.up_load(
            str(f), 0,
            progress_callback=lambda b: None,
            validation_callback=lambda p: validation_percents.append(p),
        )
        assert validation_percents
        assert validation_percents[-1] == 100


class TestUploadThreadValidationStatus:
    """UploadThread 校验阶段状态文本。"""

    def test_status_validating_emitted(self, tmp_path, tmp_db):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        _app = QApplication.instance() or QApplication([])

        from src.app.common.i18n import tr
        from src.app.tasks.transfer_tasks import UploadTask, UploadThread

        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * (1024 * 1024))
        task = UploadTask("f.bin", f.stat().st_size, str(f), 0)
        task.task_id = None  # 跳过 TransferStore 查询
        pan = MagicMock()
        pan.parent_file_id = 0

        def _up_load(local_path, task=None, resume_info=None,
                     session_callback=None, num_threads=1,
                     progress_callback=None, validation_callback=None):
            # 模拟 MD5 校验进度 → 上传中
            if validation_callback:
                for p in (10, 50, 90):
                    validation_callback(p)
                validation_callback(100)
            if progress_callback:
                progress_callback(task.task.file_size)
            return 1

        pan.up_load.side_effect = _up_load

        thread = UploadThread(task, pan)
        statuses = []
        thread.status_updated.connect(lambda s: statuses.append(s))
        thread.finished.connect(lambda: None)
        # 同步执行 run()，避免依赖事件循环
        thread.run()

        assert any(s.startswith(tr("transfer.status_validating", "校验中")) for s in statuses)
        assert any(s == tr("transfer.status_uploading", "上传中") for s in statuses)
        assert any(s == tr("transfer.status_completed", "已完成") for s in statuses)
