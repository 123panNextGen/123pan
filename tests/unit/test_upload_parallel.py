"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import threading
from unittest.mock import MagicMock

import pytest
import requests
from PySide6.QtWidgets import QApplication

from src.app.common.utils import format_speed
from src.app.service.upload_service import UploadService
from src.app.tasks import transfer_tasks as tt
from src.app.tasks.transfer_tasks import _measure_speed

_app = QApplication.instance() or QApplication([])

BLOCK = 5242880


class MockResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _mock_upload_session(uploaded_parts=None):
    """与 test_transfer_speed_limit_cancel 相同的最小上传会话 mock。

    uploaded_parts: 续传场景下服务端已上传的分片号列表。
    """
    uploaded_parts = uploaded_parts or []
    session = MagicMock()

    def _post_side_effect(url, *args, **kwargs):
        url = str(url)
        if "upload_request" in url:
            return MockResponse({
                "code": 0,
                "data": {
                    "Reuse": False,
                    "Bucket": "nb", "StorageNode": "ns", "Key": "nk",
                    "UploadId": "nu", "FileId": 7,
                },
            })
        if "s3_list_upload_parts" in url:
            return MockResponse(
                {"code": 0, "data": {"parts": [
                    {"PartNumber": pn} for pn in uploaded_parts
                ]}}
            )
        if "s3_repare_upload_parts_batch" in url:
            return MockResponse(
                {"code": 0, "data": {"presignedUrls": {
                    str(i): f"http://cdn/{i}" for i in range(1, 32)
                }}}
            )
        if "s3_complete_multipart_upload" in url:
            return MockResponse({"code": 0})
        if "upload_complete" in url:
            return MockResponse({"code": 0})
        return MockResponse({"code": 0})

    session.http.post.side_effect = _post_side_effect
    return session


class _CancellableTask:
    """模拟 UploadThread 的最小取消/暂停控制对象。"""

    def __init__(self):
        self.cancelled = False
        self._pause = threading.Event()
        self._pause.set()

    @property
    def is_cancelled(self):
        return self.cancelled

    def wait_if_paused(self):
        self._pause.wait()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()


class TestUploadParallel:
    def test_parallel_uploads_all_parts(self, tmp_path):
        """并行上传：num_threads=2 上传全部 3 个分片。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 3)
        session = _mock_upload_session()
        svc = UploadService(session)

        result = svc.up_load(str(f), 0, num_threads=2)

        assert result == 7
        assert session.transfer.put.call_count == 3
        # 批量 URL 请求次数应远小于分片数（一次请求覆盖多个分片）
        url_reqs = [
            c for c in session.http.post.call_args_list
            if "s3_repare_upload_parts_batch" in str(c.args[0])
        ]
        assert 0 < len(url_reqs) <= 2

    def test_parallel_matches_sequential_part_count(self, tmp_path):
        """并行与顺序上传上传的分片数一致（结果兼容）。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 3)
        seq_session = _mock_upload_session()
        par_session = _mock_upload_session()
        UploadService(seq_session).up_load(str(f), 0)  # 默认顺序
        UploadService(par_session).up_load(str(f), 0, num_threads=3)
        assert seq_session.transfer.put.call_count == 3
        assert par_session.transfer.put.call_count == 3

    def test_parallel_resume_skips_uploaded(self, tmp_path):
        """并行续传：跳过已上传分片 1/2，只上传分片 3。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 3)
        session = _mock_upload_session(uploaded_parts=[1, 2])
        svc = UploadService(session)
        resume_info = {
            "bucket": "b", "storage_node": "s", "upload_key": "k",
            "upload_id": "u", "up_file_id": 9,
            "file_mtime": f.stat().st_mtime, "file_size": f.stat().st_size,
            "block_size": BLOCK,
        }

        result = svc.up_load(str(f), 0, resume_info=resume_info, num_threads=2)

        assert result == 9
        assert session.transfer.put.call_count == 1
        # 续传复用会话，不应调用 upload_request
        for call in session.http.post.call_args_list:
            assert "upload_request" not in str(call.args[0])

    def test_parallel_progress_callback_reports_bytes(self, tmp_path):
        """并行上传进度回调收到累计字节数，末次等于文件大小。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 2)
        session = _mock_upload_session()
        svc = UploadService(session)
        received = []

        def _on_progress(uploaded_bytes):
            received.append(uploaded_bytes)

        svc.up_load(str(f), 0, num_threads=2, progress_callback=_on_progress)

        assert received[0] == 0  # 初始上报
        assert received[-1] == f.stat().st_size
        assert received == sorted(received)

    def test_parallel_cancel_stops_without_complete(self, tmp_path):
        """并行上传中途取消：不再完成，不调用完成接口。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 3)
        session = _mock_upload_session()
        svc = UploadService(session)
        task = _CancellableTask()

        def _put_side_effect(url, *args, **kwargs):
            task.cancelled = True  # 第一个分片上传后取消

        session.transfer.put.side_effect = _put_side_effect

        result = svc.up_load(str(f), 0, task=task, num_threads=2)

        assert result == "已取消"
        assert session.transfer.put.call_count >= 1
        urls = [str(c.args[0]) for c in session.http.post.call_args_list]
        assert not any("upload_complete" in u for u in urls)
        assert not any("s3_complete_multipart_upload" in u for u in urls)

    def test_upload_retries_transient_write_timeout(self, tmp_path):
        """分片写超时后重试，成功后继续完成上传。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK)
        session = _mock_upload_session()
        session.transfer.put.side_effect = [
            requests.exceptions.ConnectionError(
                "Connection aborted: write timeout"
            ),
            None,
        ]
        svc = UploadService(session)

        result = svc.up_load(str(f), 0)

        assert result == 7
        assert session.transfer.put.call_count == 2

    def test_complete_failure_is_not_reported_as_success(self, tmp_path):
        """服务端合并失败时抛错，不能继续确认上传完成。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK)
        session = _mock_upload_session()
        original_post = session.http.post.side_effect

        def _post_side_effect(url, *args, **kwargs):
            if "s3_complete_multipart_upload" in str(url):
                return MockResponse({"code": 5001, "message": "merge failed"})
            return original_post(url, *args, **kwargs)

        session.http.post.side_effect = _post_side_effect
        svc = UploadService(session)

        with pytest.raises(RuntimeError, match="合并上传分片失败"):
            svc.up_load(str(f), 0)

        urls = [str(c.args[0]) for c in session.http.post.call_args_list]
        assert not any("upload_complete" in url for url in urls)


class TestFormatSpeed:
    def test_zero_or_negative_is_placeholder(self):
        assert format_speed(0) == "--"
        assert format_speed(-5) == "--"

    def test_rates(self):
        assert format_speed(1536) == "1.5 KB/s"
        assert format_speed(3 * 1024 * 1024) == "3.0 MB/s"


class TestMeasureSpeed:
    def test_first_call_returns_zero(self, monkeypatch):
        clock = [100.0]
        monkeypatch.setattr(tt.time, "monotonic", lambda: clock[0])
        speed, ts, b = _measure_speed(None, 0, 0.0, 1024)
        assert speed == 0.0
        assert ts == 100.0
        assert b == 1024

    def test_short_interval_keeps_current_speed(self, monkeypatch):
        clock = [100.0]
        monkeypatch.setattr(tt.time, "monotonic", lambda: clock[0])
        _, ts, b = _measure_speed(None, 0, 0.0, 1024)
        clock[0] = 100.2  # 0.2s，小于 0.5s 采样窗口
        speed, ts2, b2 = _measure_speed(ts, b, 5.0, 1300)
        assert speed == 5.0
        assert ts2 == 100.0
        assert b2 == 1024

    def test_rate_computed_after_interval(self, monkeypatch):
        clock = [100.0]
        monkeypatch.setattr(tt.time, "monotonic", lambda: clock[0])
        _, ts, b = _measure_speed(None, 0, 0.0, 1024)
        clock[0] = 100.6  # 0.6s 后
        speed, ts2, b2 = _measure_speed(ts, b, 0.0, 2048)
        assert speed == pytest.approx((2048 - 1024) / 0.6)
        assert ts2 == 100.6
        assert b2 == 2048


class TestThreadCountPlumbing:
    def test_download_multi_thread_passes_num_threads(self):
        from src.app.common.api import Pan123

        pan = object.__new__(Pan123)
        pan._download = MagicMock()
        pan.set_download_multi_thread(True, 8)
        pan._download.set_multi_thread.assert_called_once_with(True, 8)

    def test_upload_thread_applies_config_thread_count(self, tmp_db):
        """UploadThread 启动时读取 uploadThreadCount 并传给 up_load。"""
        from src.app.common.config import ConfigManager
        from src.app.tasks.transfer_tasks import UploadThread

        ConfigManager.set_setting("uploadThreadCount", 3)
        task = MagicMock()
        task.file_name = "f.bin"
        task.file_size = BLOCK
        task.local_path = "/tmp/f.bin"
        task.target_dir_id = 0
        task.task_id = None
        task.speed = 0.0
        pan = MagicMock()
        pan.parent_file_id = 0

        th = UploadThread(task, pan)
        th.start()
        th.wait(3000)

        kwargs = pan.up_load.call_args.kwargs
        assert kwargs.get("num_threads") == 3

    def test_upload_thread_caps_config_thread_count(self, tmp_db):
        """旧配置超过上限时，上传线程数最多为 4。"""
        from src.app.common.config import ConfigManager
        from src.app.tasks.transfer_tasks import UploadThread

        ConfigManager.set_setting("uploadThreadCount", 16)
        task = MagicMock()
        task.file_name = "f.bin"
        task.file_size = BLOCK
        task.local_path = "/tmp/f.bin"
        task.target_dir_id = 0
        task.task_id = None
        task.speed = 0.0
        pan = MagicMock()

        th = UploadThread(task, pan)
        th.start()
        th.wait(3000)

        assert pan.up_load.call_args.kwargs.get("num_threads") == 4

    def test_download_thread_applies_config_thread_count(self, tmp_db):
        """DownloadThread 启动时读取 downloadThreadCount 并应用。"""
        from src.app.common.config import ConfigManager
        from src.app.tasks.transfer_tasks import DownloadThread

        ConfigManager.set_setting("downloadThreadCount", 6)
        task = MagicMock()
        task.file_name = "f.bin"
        task.file_id = 1
        task.file_size = BLOCK
        task.save_path = "/tmp/f.bin"
        task.current_dir_id = 0
        task.speed = 0.0
        pan = MagicMock()
        pan.link_by_fileDetail.return_value = "http://cdn/f.bin"
        pan.download_file.return_value = True
        pan.get_dir_by_id.return_value = (0, [])
        pan.list = []

        th = DownloadThread(task, pan)
        th.start()
        th.wait(3000)

        pan.set_download_multi_thread.assert_called_once_with(True, 6)
