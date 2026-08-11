"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock

import pytest

from src.app.service.offline_service import OfflineService


class MockResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _make_session():
    session = MagicMock()
    session.http.post.return_value = MockResponse({"code": 0, "data": {}})
    return session


class TestParseRapidJson:
    """解析秒传 JSON（夸克/天翼等导出的数据）。"""

    def _svc(self):
        return OfflineService(_make_session())

    def test_standard_json(self):
        svc = self._svc()
        text = (
            '{"scriptVersion":"3.0.3","exportVersion":"1.0",'
            '"usesBase62EtagsInExport":false,"commonPath":"",'
            '"files":[{"path":"a.txt","etag":"d41d8cd98f00b204e9800998ecf8427e",'
            '"size":100},{"path":"dir/b.txt","etag":"e2fc714c4727ee9395f324cd2e7f331f",'
            '"size":200}]}'
        )
        files = svc.parse_rapid_data(text)
        assert len(files) == 2
        assert files[0]["path"] == "a.txt"
        assert files[0]["etag"] == "d41d8cd98f00b204e9800998ecf8427e"
        assert files[0]["size"] == 100
        assert files[1]["path"] == "dir/b.txt"

    def test_common_path_prefix(self):
        svc = self._svc()
        text = (
            '{"commonPath":"folder/","files":[{"path":"a.txt",'
            '"etag":"d41d8cd98f00b204e9800998ecf8427e","size":100}]}'
        )
        files = svc.parse_rapid_data(text)
        assert files[0]["path"] == "folder/a.txt"

    def test_base62_etags(self):
        svc = self._svc()
        text = (
            '{"usesBase62EtagsInExport":true,"files":['
            '{"path":"a.txt","etag":"6sfSqfOwzkG7dz3i6Vldpk","size":100}]}'
        )
        files = svc.parse_rapid_data(text)
        # Base62 解码 = md5 of empty string
        assert files[0]["etag"] == "d41d8cd98f00b204e9800998ecf8427e"

    def test_invalid_etag_skipped(self):
        svc = self._svc()
        text = (
            '{"files":[{"path":"bad.txt","etag":"zz","size":100},'
            '{"path":"ok.txt","etag":"d41d8cd98f00b204e9800998ecf8427e","size":1}]}'
        )
        files = svc.parse_rapid_data(text)
        assert len(files) == 1
        assert files[0]["path"] == "ok.txt"

    def test_invalid_json(self):
        svc = self._svc()
        with pytest.raises(ValueError):
            svc.parse_rapid_data('{"files": []}')
        with pytest.raises(ValueError):
            svc.parse_rapid_data("not json")


class TestParseRapidLink:
    """解析文本秒传链接。"""

    def _svc(self):
        return OfflineService(_make_session())

    def test_standard_link(self):
        svc = self._svc()
        # 123FLCPV2$folder/%etag#size#path
        link = (
            "123FLCPV2$folder/"
            "%d41d8cd98f00b204e9800998ecf8427e#100#a.txt"
            "$e2fc714c4727ee9395f324cd2e7f331f#200#dir/b.txt"
        )
        files = svc.parse_rapid_data(link)
        assert len(files) == 2
        assert files[0]["path"] == "folder/a.txt"
        assert files[1]["path"] == "folder/dir/b.txt"

    def test_base62_link(self):
        svc = self._svc()
        link = (
            "123FLCPV2$%6sfSqfOwzkG7dz3i6Vldpk#100#a.txt"
        )
        files = svc.parse_rapid_data(link)
        assert files[0]["etag"] == "d41d8cd98f00b204e9800998ecf8427e"

    def test_legacy_link_no_prefix(self):
        svc = self._svc()
        link = (
            "d41d8cd98f00b204e9800998ecf8427e#100#a.txt\n"
            "e2fc714c4727ee9395f324cd2e7f331f#200#b.txt"
        )
        files = svc.parse_rapid_data(link)
        assert len(files) == 2
        assert files[0]["path"] == "a.txt"

    def test_unsupported_prefix(self):
        svc = self._svc()
        with pytest.raises(ValueError):
            svc.parse_rapid_data("OTHER$x%y#1#z")


class TestFastUpload:
    """秒传单文件。"""

    def _svc(self, reuse=True, file_id=99):
        session = MagicMock()

        def _post(url, *args, **kwargs):
            if reuse:
                return MockResponse({
                    "code": 0,
                    "data": {"Reuse": True, "FileId": file_id},
                })
            return MockResponse({"code": 0, "data": {"Reuse": False}})

        session.http.post.side_effect = _post
        return OfflineService(session)

    def test_reuse_success(self):
        svc = self._svc(reuse=True, file_id=42)
        fid = svc._upload.fast_upload("a.txt", 100,
                                      "d41d8cd98f00b204e9800998ecf8427e", 0)
        assert fid == 42

    def test_no_reuse_returns_none(self):
        svc = self._svc(reuse=False)
        fid = svc._upload.fast_upload("a.txt", 100,
                                      "d41d8cd98f00b204e9800998ecf8427e", 0)
        assert fid is None

    def test_api_error_raises(self):
        session = MagicMock()
        session.http.post.return_value = MockResponse({"code": 500, "message": "err"})
        svc = OfflineService(session)
        with pytest.raises(RuntimeError):
            svc._upload.fast_upload("a.txt", 100,
                                    "d41d8cd98f00b204e9800998ecf8427e", 0)


class TestRapidTransfer:
    """秒传导入（建目录 + 逐个秒传）。"""

    def test_transfer_with_folders(self, tmp_db):
        session = MagicMock()
        session.http.post.return_value = MockResponse({
            "code": 0,
            "data": {"Reuse": True, "FileId": 7},
        })
        svc = OfflineService(session)

        # 根目录 0 下已有文件夹 "folder"（FileId=100）
        def _get_dir(dir_id, **kw):
            if int(dir_id) == 0:
                return 0, [{"FileId": 100, "FileName": "folder", "Type": 1}]
            return 0, []

        svc._file.get_dir_by_id = MagicMock(side_effect=_get_dir)
        created = []

        def _create_folder(name, parent):
            created.append((name, parent))
            return (300 + len(created), "")

        svc._file.create_folder = MagicMock(side_effect=_create_folder)

        files = [
            {"path": "folder/sub/a.txt", "etag": "d41d8cd98f00b204e9800998ecf8427e", "size": 100},
            {"path": "b.txt", "etag": "e2fc714c4727ee9395f324cd2e7f331f", "size": 200},
        ]
        stats = svc.rapid_transfer(files, 0)
        assert len(stats["success"]) == 2
        assert stats["failed"] == []
        # folder 复用（未创建），sub 新建
        assert ("sub", 100) in created

    def test_transfer_reuse_same_folder_not_duplicated(self, tmp_db):
        session = MagicMock()
        session.http.post.return_value = MockResponse({
            "code": 0,
            "data": {"Reuse": True, "FileId": 7},
        })
        svc = OfflineService(session)
        svc._file.get_dir_by_id = MagicMock(return_value=(0, []))
        svc._file.create_folder = MagicMock(
            side_effect=lambda name, parent: ((parent * 10 + 1), "")
        )

        files = [
            {"path": "dir/a.txt", "etag": "d41d8cd98f00b204e9800998ecf8427e", "size": 1},
            {"path": "dir/b.txt", "etag": "e2fc714c4727ee9395f324cd2e7f331f", "size": 2},
        ]
        stats = svc.rapid_transfer(files, 0)
        assert len(stats["success"]) == 2
        # dir 只创建一次
        assert svc._file.create_folder.call_count == 1


class TestOfflineResolveSubmit:
    """离线下载解析/提交 API。"""

    def test_resolve_success(self):
        session = _make_session()
        session.http.post.return_value = MockResponse({
            "code": 0,
            "data": {"list": [{"url": "magnet:x", "type": "magnet", "result": 0,
                               "name": "f.iso", "size": 100, "id": 5, "files": []}]},
        })
        svc = OfflineService(session)
        result = svc.resolve("magnet:x")
        assert len(result) == 1
        assert result[0]["id"] == 5

    def test_resolve_error(self):
        session = _make_session()
        session.http.post.return_value = MockResponse({"code": 500, "message": "boom"})
        svc = OfflineService(session)
        with pytest.raises(RuntimeError):
            svc.resolve("bad-url")

    def test_submit_success(self):
        session = _make_session()
        session.http.post.return_value = MockResponse({
            "code": 0,
            "data": {"task_list": [{"task_id": 10, "result": 0}]},
        })
        svc = OfflineService(session)
        task_list = svc.submit([{"resource_id": 5, "select_file_id": []}])
        assert task_list[0]["task_id"] == 10
