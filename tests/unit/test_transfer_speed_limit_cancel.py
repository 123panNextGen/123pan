"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from src.app.api.download_engine import DownloadCancelledError
from src.app.api.session import NetSession
from src.app.service.upload_service import UploadService
from src.app.tasks.transfer_tasks import DownloadThread, UploadTask, UploadThread

_app = QApplication.instance() or QApplication([])

BLOCK = 5242880


class MockResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _mock_upload_session():
    """与 test_upload_resume 相同的最小上传会话 mock。"""
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
            return MockResponse({"code": 0, "data": {"parts": []}})
        if "s3_repare_upload_parts_batch" in url:
            return MockResponse(
                {"code": 0, "data": {"presignedUrls": {
                    str(i): f"http://cdn/{i}" for i in range(1, 16)
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
    """模拟 UploadThread 的最小取消控制对象。"""

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


class TestUploadSpeedLimit:
    def test_upload_speed_limited(self, tmp_path):
        """限速后上传 2 个分片（10MB）至少耗时一个等待周期。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 2)
        session = _mock_upload_session()
        svc = UploadService(session)
        # 4096 KB/s：令牌桶容量 2s=8192KB，第 2 个分片(5120KB)需等待 0.5s
        svc.set_upload_speed_limit(4096)

        t0 = time.monotonic()
        result = svc.up_load(str(f), 0)
        elapsed = time.monotonic() - t0

        assert result == 7
        assert elapsed >= 0.4, f"限速未生效，仅耗时 {elapsed:.3f}s"
        assert session.transfer.put.call_count == 2

    def test_upload_without_limiter_fast(self, tmp_path):
        """不限速时同样上传应在毫秒级完成，证明限速是有效行为。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 2)
        session = _mock_upload_session()
        svc = UploadService(session)

        t0 = time.monotonic()
        svc.up_load(str(f), 0)
        elapsed = time.monotonic() - t0

        assert elapsed < 0.3, f"mock 上传不应耗时，实际 {elapsed:.3f}s"


class TestUploadCancel:
    def test_cancel_before_start(self, tmp_path):
        """上传开始前已取消：直接返回，不发起任何请求。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK)
        session = _mock_upload_session()
        svc = UploadService(session)
        task = _CancellableTask()
        task.cancelled = True

        result = svc.up_load(str(f), 0, task=task)

        assert result == "已取消"
        session.http.post.assert_not_called()

    def test_cancel_mid_chunks(self, tmp_path):
        """上传第 1 个分片后取消：停止后续分片，不再调用完成接口。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 2)
        session = _mock_upload_session()
        svc = UploadService(session)
        task = _CancellableTask()

        def _put_side_effect(url, *args, **kwargs):
            task.cancelled = True  # 第 1 个分片上传后取消

        session.transfer.put.side_effect = _put_side_effect

        result = svc.up_load(str(f), 0, task=task)

        assert result == "已取消"
        assert session.transfer.put.call_count == 1
        urls = [str(c.args[0]) for c in session.http.post.call_args_list]
        assert not any("upload_complete" in u for u in urls)
        assert not any("s3_complete_multipart_upload" in u for u in urls)


class TestUploadPause:
    def test_pause_blocks_then_resumes(self, tmp_path):
        """暂停后分片循环阻塞，恢复后继续完成上传。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 3)
        session = _mock_upload_session()
        svc = UploadService(session)
        task = _CancellableTask()
        task.pause()

        errors = []

        def _run():
            try:
                return svc.up_load(str(f), 0, task=task)
            except Exception as e:
                errors.append(e)

        th = threading.Thread(target=_run)
        th.start()
        time.sleep(0.3)
        # 暂停期间应阻塞在 wait_if_paused，尚未完成
        assert th.is_alive(), "暂停未生效：上传线程不应存活"

        task.resume()
        th.join(timeout=5)
        assert not th.is_alive()
        assert errors == []
        # 恢复后 3 个分片全部上传
        assert session.transfer.put.call_count == 3


class FakeStreamResponse:
    """流式下载响应：写出若干 chunk 后在指定 chunk 前置位取消事件。"""

    def __init__(self, chunk_count, cancel_chunk_index, cancel_event):
        self._chunk_count = chunk_count
        self._cancel_chunk_index = cancel_chunk_index
        self._cancel_event = cancel_event

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    @property
    def headers(self):
        return {"Content-Type": "application/octet-stream"}

    def iter_content(self, chunk_size=8192):
        for i in range(self._chunk_count):
            if i >= self._cancel_chunk_index:
                self._cancel_event.set()
            yield b"x" * chunk_size


class TestDownloadCancel:
    def _make_session(self, chunk_count=4, cancel_chunk_index=2, chunk_size=8192):
        session = NetSession()
        cancel_event = threading.Event()
        body = FakeStreamResponse(chunk_count, cancel_chunk_index, cancel_event)
        session._transfer.get = MagicMock(return_value=body)
        return session, cancel_event, chunk_count * chunk_size

    def test_download_single_cancel_keeps_temp(self, tmp_path):
        """单线程下载取消：返回 False，.tmp 保留供续传，目标文件不存在。"""
        session, cancel_event, file_size = self._make_session()
        file_path = tmp_path / "dl.bin"

        ok = session.download_file_multithread(
            "https://cdn.example.com/dl.bin", file_path, file_size,
            cancel_event=cancel_event,
        )

        assert ok is False
        assert not file_path.exists()
        # 取消点在写出 2 个 chunk 之后，临时文件保留已下载数据
        assert file_path.with_suffix(".bin.tmp").exists()
        assert file_path.with_suffix(".bin.tmp").stat().st_size == 2 * 8192

    def test_download_chunked_cancel_cleans_parts(self, tmp_path, monkeypatch):
        """多线程分片下载取消：返回 False，分片临时文件被清理。"""
        session, cancel_event, file_size = self._make_session(
            chunk_count=600, cancel_chunk_index=1, chunk_size=16384
        )
        session._num_threads = 4
        # 绕过真实 HEAD 预检与 JSON 重定向，直接进入分片路径
        monkeypatch.setattr(session, "_check_range_support", lambda url: True)
        monkeypatch.setattr(session, "_resolve_json_redirect_url", lambda url: "")
        file_path = tmp_path / "mt.bin"

        ok = session.download_file_multithread(
            "https://cdn.example.com/mt.bin", file_path, file_size,
            cancel_event=cancel_event,
        )

        assert ok is False
        assert not file_path.exists()
        leftovers = list(tmp_path.glob("mt.bin.tmp*"))
        assert leftovers == []

    def test_download_cancel_without_event_completes(self, tmp_path):
        """不传取消事件时行为不变：下载完成。"""
        session, _, file_size = self._make_session(cancel_chunk_index=10 ** 9)
        file_path = tmp_path / "ok.bin"

        ok = session.download_file_multithread(
            "https://cdn.example.com/ok.bin", file_path, file_size,
        )

        assert ok is True
        assert file_path.exists()
        assert file_path.stat().st_size == file_size


class TestTransferThreadControls:
    def _upload_thread(self):
        task = MagicMock()
        task.file_name = "f.bin"
        task.file_size = BLOCK
        task.local_path = "C:/f.bin"
        task.target_dir_id = 0
        task.task_id = None
        pan = MagicMock()
        pan.parent_file_id = 0
        return UploadThread(task, pan), task, pan

    def test_upload_thread_cancel_flag(self):
        th, _, _ = self._upload_thread()
        assert th.is_cancelled is False
        th.cancel()
        assert th.is_cancelled is True

    def test_upload_speed_has_start_time(self):
        task = UploadTask("a.txt", 10, "/tmp/a.txt", 0)
        thread = UploadThread(task, MagicMock())
        assert thread._speed_ts is not None

    def test_upload_thread_wait_if_paused(self):
        th, _, _ = self._upload_thread()
        th.pause()

        result = []
        worker = threading.Thread(target=lambda: result.append(th.wait_if_paused()))
        worker.start()
        time.sleep(0.2)
        assert worker.is_alive(), "暂停后 wait_if_paused 应阻塞"

        th.resume()
        worker.join(timeout=2)
        assert not worker.is_alive()

    def test_download_thread_cancel_event(self):
        task = MagicMock()
        task.file_name = "f.bin"
        task.file_id = 1
        task.file_size = BLOCK
        pan = MagicMock()
        th = DownloadThread(task, pan)

        assert th._cancel_event.is_set() is False
        th.cancel()
        assert th._cancelled is True
        assert th._cancel_event.is_set() is True
        assert th._pause_event.is_set() is True
