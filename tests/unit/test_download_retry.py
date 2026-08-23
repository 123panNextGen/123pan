"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import pytest
import requests
import responses

from src.app.api import download_engine as de
from src.app.api.session import NetSession


class TestThrottleHelpers:
    """限流识别与退避计算辅助函数。"""

    @staticmethod
    def _http_error(status, headers=None):
        resp = requests.Response()
        resp.status_code = status
        resp.headers = headers or {}
        return requests.exceptions.HTTPError(
            f"{status} Client Error", response=resp
        )

    def test_is_throttle_error_429(self):
        assert de._is_throttle_error(self._http_error(429)) is True

    def test_is_throttle_error_5xx(self):
        assert de._is_throttle_error(self._http_error(503)) is True

    def test_is_throttle_error_other_http_error(self):
        assert de._is_throttle_error(self._http_error(404)) is False

    def test_is_throttle_error_non_http_error(self):
        assert de._is_throttle_error(requests.exceptions.ConnectionError("x")) is False

    def test_backoff_prefers_retry_after(self):
        exc = self._http_error(429, headers={"Retry-After": "5"})
        assert de._throttle_backoff(exc, 0) == 5.0

    def test_backoff_retry_after_capped(self):
        exc = self._http_error(429, headers={"Retry-After": "300"})
        assert de._throttle_backoff(exc, 0) == 60.0

    def test_backoff_exponential_within_bounds(self):
        exc = self._http_error(429)
        wait = de._throttle_backoff(exc, 5)
        assert 30.0 <= wait < 31.0


class TestDownloadSingleRetry:
    """单线程路径对限流（429）的退避重试。"""

    @responses.activate
    def test_single_does_not_retry_when_backoff_disabled(self, tmp_path):
        session = NetSession()
        session.set_error_backoff_retry(False)
        file_path = tmp_path / "no-retry.bin"
        calls = {"n": 0}

        def cb(request):
            calls["n"] += 1
            return (429, {}, "")

        responses.add_callback(
            responses.GET,
            "https://cdn.example.com/no-retry.bin",
            callback=cb,
        )

        with pytest.raises(requests.exceptions.HTTPError):
            session._download_single(
                "https://cdn.example.com/no-retry.bin", file_path, 4
            )
        assert calls["n"] == 1

    @responses.activate
    def test_single_retries_on_429_then_succeeds(self, tmp_path, monkeypatch):
        """遇 429 时按退避重试，最终成功。"""
        monkeypatch.setattr(de, "_throttle_backoff", lambda exc, attempt: 0)

        session = NetSession()
        file_path = tmp_path / "limited.bin"
        body = b"DATA" * 100
        calls = {"n": 0}

        def cb(request):
            calls["n"] += 1
            if calls["n"] < 3:
                return (429, {}, "")
            return (200, {"Content-Type": "application/octet-stream"}, body)

        responses.add_callback(
            responses.GET,
            "https://cdn.example.com/limited.bin",
            callback=cb,
        )

        ok = session._download_single(
            "https://cdn.example.com/limited.bin", file_path, len(body)
        )
        assert ok is True
        assert calls["n"] == 3
        assert file_path.read_bytes() == body

    @responses.activate
    def test_single_gives_up_after_throttle_retries(self, tmp_path, monkeypatch):
        """持续 429 时重试耗尽后失败，并清理临时文件。"""
        monkeypatch.setattr(de, "_throttle_backoff", lambda exc, attempt: 0)

        session = NetSession()
        file_path = tmp_path / "limited2.bin"
        body = b"DATA" * 100
        calls = {"n": 0}

        def cb(request):
            calls["n"] += 1
            return (429, {}, "")

        responses.add_callback(
            responses.GET,
            "https://cdn.example.com/limited2.bin",
            callback=cb,
        )

        with pytest.raises(requests.exceptions.HTTPError):
            session._download_single(
                "https://cdn.example.com/limited2.bin", file_path, len(body)
            )
        assert calls["n"] == 6
        assert not file_path.exists()
        assert not file_path.with_suffix(".bin.tmp").exists()


class TestMultithreadFallback:
    """多线程分片失败时的单线程回退。"""

    def test_chunk_failure_does_not_fallback_when_retry_disabled(
        self, tmp_path, monkeypatch
    ):
        session = NetSession()
        session.set_error_backoff_retry(False)
        file_path = tmp_path / "no-fallback.bin"
        calls = {"single": 0}

        monkeypatch.setattr(session, "_resolve_json_redirect_url", lambda url: "")
        monkeypatch.setattr(session, "_check_range_support", lambda url: True)
        monkeypatch.setattr(
            session,
            "_download_chunked",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("429")),
        )
        monkeypatch.setattr(
            session,
            "_download_single",
            lambda *args, **kwargs: calls.update(single=calls["single"] + 1),
        )

        with pytest.raises(RuntimeError, match="429"):
            session.download_file_multithread(
                "https://cdn.example.com/no-fallback.bin",
                file_path,
                6 * 1024 * 1024,
            )
        assert calls["single"] == 0

    def test_chunk_failure_falls_back_single(self, tmp_path, monkeypatch):
        """分片持续失败（如 429）时回退单线程，而非整体失败。"""
        session = NetSession()
        session._num_threads = 4
        file_path = tmp_path / "mt.bin"
        calls = {"single": 0}

        def _chunked_fail(*args, **kwargs):
            raise RuntimeError("分片下载失败: 分片2: 429 Client Error")

        def _single_ok(*args, **kwargs):
            calls["single"] += 1
            return True

        monkeypatch.setattr(session, "_resolve_json_redirect_url", lambda url: "")
        monkeypatch.setattr(session, "_check_range_support", lambda url: True)
        monkeypatch.setattr(session, "_download_chunked", _chunked_fail)
        monkeypatch.setattr(session, "_download_single", _single_ok)

        ok = session.download_file_multithread(
            "https://cdn.example.com/mt.bin", file_path, 6 * 1024 * 1024
        )
        assert ok is True
        assert calls["single"] == 1

    def test_unexpected_chunk_error_not_hidden(self, tmp_path, monkeypatch):
        """非 RuntimeError 的异常（潜在 bug）不应被回退逻辑吞掉。"""
        session = NetSession()
        session._num_threads = 4
        file_path = tmp_path / "mt2.bin"

        def _chunked_boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(session, "_resolve_json_redirect_url", lambda url: "")
        monkeypatch.setattr(session, "_check_range_support", lambda url: True)
        monkeypatch.setattr(session, "_download_chunked", _chunked_boom)

        with pytest.raises(OSError):
            session.download_file_multithread(
                "https://cdn.example.com/mt2.bin", file_path, 6 * 1024 * 1024
            )
