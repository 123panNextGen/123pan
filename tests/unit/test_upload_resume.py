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

BLOCK = 5242880


class MockResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class TestValidateResumeInfo:
    def _make(self):
        return UploadService(MagicMock())

    def test_valid(self, tmp_path):
        svc = self._make()
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * 100)
        info = {
            "bucket": "b", "storage_node": "s", "upload_key": "k",
            "upload_id": "u", "up_file_id": 9,
            "file_mtime": f.stat().st_mtime, "file_size": 100,
        }
        assert svc._validate_resume_info(info, f, 100) is info

    def test_missing_fields(self, tmp_path):
        svc = self._make()
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * 100)
        assert svc._validate_resume_info(None, f, 100) is None
        assert svc._validate_resume_info({}, f, 100) is None
        assert svc._validate_resume_info({"bucket": "b"}, f, 100) is None

    def test_size_mismatch(self, tmp_path):
        svc = self._make()
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * 100)
        info = {
            "bucket": "b", "storage_node": "s", "upload_key": "k",
            "upload_id": "u", "up_file_id": 9,
            "file_mtime": f.stat().st_mtime, "file_size": 200,
        }
        assert svc._validate_resume_info(info, f, 100) is None

    def test_mtime_changed(self, tmp_path):
        svc = self._make()
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * 100)
        info = {
            "bucket": "b", "storage_node": "s", "upload_key": "k",
            "upload_id": "u", "up_file_id": 9,
            "file_mtime": f.stat().st_mtime - 1000, "file_size": 100,
        }
        assert svc._validate_resume_info(info, f, 100) is None


class TestUploadResume:
    def _mock_session(self):
        session = MagicMock()

        def _post_side_effect(url, *args, **kwargs):
            url = str(url)
            if "s3_list_upload_parts" in url:
                return MockResponse(
                    {"code": 0, "data": {"parts": [{"PartNumber": 1}]}}
                )
            if "s3_repare_upload_parts_batch" in url:
                return MockResponse(
                    {"code": 0, "data": {"presignedUrls": {
                        "2": "http://cdn/2", "3": "http://cdn/3", "4": "http://cdn/4"
                    }}}
                )
            if "s3_complete_multipart_upload" in url:
                return MockResponse({"code": 0})
            if "upload_complete" in url:
                return MockResponse({"code": 0})
            return MockResponse({"code": 0})

        session.http.post.side_effect = _post_side_effect
        session.http.post.return_value = MockResponse({"code": 0})
        return session

    def test_resume_skips_upload_request(self, tmp_path):
        """续传时不调用 upload_request，且跳过已上传分片。"""
        f = tmp_path / "f.bin"
        f.write_bytes(b"A" * BLOCK * 2 + b"B" * 100)  # 2 完整块 + 1 部分块
        session = self._mock_session()
        svc = UploadService(session)

        resume_info = {
            "bucket": "b", "storage_node": "s", "upload_key": "k",
            "upload_id": "u", "up_file_id": 9,
            "file_mtime": f.stat().st_mtime, "file_size": f.stat().st_size,
            "block_size": BLOCK,
        }
        result = svc.up_load(str(f), 0, resume_info=resume_info)
        assert result == 9

        # 不应调用 upload_request
        for call in session.http.post.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url")
            assert "upload_request" not in str(url)
        # 跳过已上传分片 1，剩余 2 个分片上传（2*BLOCK+100）
        assert session.transfer.put.call_count == 2
        # 回调持久化不应触发（续传复用会话）
        callback = MagicMock()
        svc.up_load(str(f), 0, resume_info=resume_info, session_callback=callback)
        callback.assert_not_called()

    def test_fresh_upload_calls_upload_request_and_callback(self, tmp_path):
        """全新上传调用 upload_request 并回调持久化会话。"""
        f = tmp_path / "g.bin"
        f.write_bytes(b"A" * BLOCK)  # 1 块
        session = self._mock_session()
        svc = UploadService(session)

        # 覆盖 upload_request 返回新会话
        calls = []

        def _post_side_effect(url, *args, **kwargs):
            url = str(url)
            calls.append(url)
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
                    {"code": 0, "data": {"presignedUrls": {"1": "http://cdn/1"}}}
                )
            if "s3_complete_multipart_upload" in url:
                return MockResponse({"code": 0})
            if "upload_complete" in url:
                return MockResponse({"code": 0})
            return MockResponse({"code": 0})

        session.http.post.side_effect = _post_side_effect

        callback = MagicMock()
        result = svc.up_load(str(f), 0, session_callback=callback)
        assert result == 7
        assert any("upload_request" in c for c in calls)
        assert session.transfer.put.call_count == 1
        # 回调收到 S3 会话信息
        assert callback.call_count == 1
        info = callback.call_args[0][0]
        assert info["upload_id"] == "nu"
        assert info["file_size"] == f.stat().st_size
