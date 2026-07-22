"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import io

import requests
import responses

from src.app.api.model import ApiCode
from src.app.api.session import NetSession


class TestNetSessionSetters:
    def test_set_multi_thread(self):
        session = NetSession()
        assert session._multi_thread_enabled is True
        assert session._num_threads == 4

        session.set_multi_thread(False, 8)
        assert session._multi_thread_enabled is False
        assert session._num_threads == 8

    def test_set_multi_thread_clamp(self):
        session = NetSession()
        session.set_multi_thread(True, 99)
        assert session._num_threads == 16

        session.set_multi_thread(True, 0)
        assert session._num_threads == 1

    def test_set_speed_limiter(self):
        session = NetSession()
        limiter = object()
        session.set_speed_limiter(limiter, is_upload=False)
        assert session._download_limiter is limiter
        assert session._upload_limiter is None

        limiter2 = object()
        session.set_speed_limiter(limiter2, is_upload=True)
        assert session._upload_limiter is limiter2

    def test_set_progress_callback(self):
        session = NetSession()

        def cb(d, t):
            pass

        session.set_progress_callback(cb)
        assert session._progress_callback is cb
        session.set_progress_callback(None)
        assert session._progress_callback is None

    def test_set_proxy(self):
        session = NetSession()
        session.set_proxy("http://127.0.0.1:8080")
        assert session._http.proxies.get("http") == "http://127.0.0.1:8080"
        assert session._http.proxies.get("https") == "http://127.0.0.1:8080"

    def test_set_proxy_clear(self):
        session = NetSession()
        session.set_proxy("http://127.0.0.1:8080")
        session.set_proxy("")
        assert session._http.proxies == {}
        assert session._transfer.proxies == {}

    def test_set_proxy_auth(self):
        session = NetSession()
        session.set_proxy_auth("http", "proxy.example.com", 3128, "user", "pass")
        assert session._http.proxies.get("http") == "http://user:pass@proxy.example.com:3128"


class TestNetSessionSafeJson:
    def test_valid_json(self):
        resp = requests.Response()
        resp.status_code = 200
        body = '{"code": 200, "message": "ok"}'
        resp.raw = io.BytesIO(body.encode())
        resp.encoding = "utf-8"
        resp._content = body.encode()

        parsed, error = NetSession._safe_json(resp)
        assert parsed == {"code": 200, "message": "ok"}
        assert error is None

    def test_invalid_json(self):
        resp = requests.Response()
        resp.status_code = 500
        resp._content = b"<html>error</html>"

        parsed, error = NetSession._safe_json(resp)
        assert parsed == {}
        assert error is not None
        assert error.code == -1
        assert "JSON" in error.msg or "无效" in error.msg


class TestNetSessionHttp:
    @responses.activate
    def test_login_success(self):
        responses.post(
            "https://www.123pan.cn/b/api/user/sign_in",
            json={"code": 200, "data": {"token": "test_token"}},
            status=200,
            headers={"Set-Cookie": "session=abc123"},
        )
        session = NetSession()
        result = session.login("test_user", "test_pass")
        assert result.code == 200
        assert result.api_code_enum == ApiCode.success
        assert result.data["token"] == "test_token"
        assert result.data["authorization"] == "Bearer test_token"
        assert session.user_info is not None
        assert session.user_info.user_name == "test_user"
        assert session.authorization == "Bearer test_token"

    @responses.activate
    def test_login_invalid_credentials(self):
        responses.post(
            "https://www.123pan.cn/b/api/user/sign_in",
            json={"code": 401, "message": "用户名或密码错误"},
            status=200,
        )
        session = NetSession()
        result = session.login("bad_user", "bad_pass")
        assert result.code == 401
        assert result.api_code_enum == ApiCode.fail

    @responses.activate
    def test_login_network_error(self):
        responses.post(
            "https://www.123pan.cn/b/api/user/sign_in",
            body=requests.exceptions.ConnectionError("connection refused"),
        )
        session = NetSession()
        result = session.login("test_user", "test_pass")
        assert result.code == -1
        assert result.api_code_enum == ApiCode.fail
        assert "connection refused" in result.msg.lower()

    @responses.activate
    def test_get_file_list(self):
        responses.get(
            "https://www.123pan.cn/api/file/list/new",
            json={
                "code": 0,
                "message": "",
                "data": {
                    "Next": "-1",
                    "Len": 1,
                    "Total": 1,
                    "IsFirst": True,
                    "InfoList": [
                        {
                            "FileId": 1,
                            "FileName": "test.txt",
                            "Type": 0,
                            "Size": 100,
                            "CreateAt": 1700000000,
                            "UpdateAt": 1700000000,
                            "Hidden": False,
                            "Etag": "",
                            "S3KeyFlag": "",
                            "ContentType": "",
                            "ParentFileId": 0,
                            "PinYin": "",
                            "StarredStatus": False,
                        }
                    ],
                },
            },
            status=200,
        )
        session = NetSession()
        result = session.get_file_list(file_id=0, reverse=False, trashed=False, page=1, limit=100)
        assert result.code == 0
        assert result.api_code_enum == ApiCode.success
        flr = result.data
        assert flr.data.total == 1
        assert len(flr.data.info_list) == 1
        assert flr.data.info_list[0].file_name == "test.txt"

    @responses.activate
    def test_get_file_list_empty(self):
        responses.get(
            "https://www.123pan.cn/api/file/list/new",
            json={"code": 0, "message": "", "data": {"Next": "-1", "Len": 0, "Total": 0, "IsFirst": True, "InfoList": []}},
            status=200,
        )
        session = NetSession()
        result = session.get_file_list(file_id=0)
        assert result.code == 0
        assert len(result.data.data.info_list) == 0

    @responses.activate
    def test_create_dir_success(self):
        responses.post(
            "https://www.123pan.cn/a/api/file/upload_request",
            json={"code": 0, "data": {"fileId": 100}},
            status=200,
        )
        session = NetSession()
        result = session.create_dir("new_folder", parent_file_id=0)
        assert result.code == 0
        assert result.data["fileId"] == 100

    @responses.activate
    def test_create_dir_failure(self):
        responses.post(
            "https://www.123pan.cn/a/api/file/upload_request",
            json={"code": 400, "message": "目录名已存在"},
            status=200,
        )
        session = NetSession()
        result = session.create_dir("existing_folder", parent_file_id=0)
        assert result.code == 400
        assert "已存在" in result.msg

    @responses.activate
    def test_get_file_link(self, mocker):
        responses.post(
            "https://www.123pan.cn/a/api/file/download_info",
            json={"code": 0, "data": {"DownloadUrl": "https://cdn.example.com/file"}},
            status=200,
        )
        session = NetSession()
        mocker.patch.object(session, "_resolve_download_url", return_value="https://resolved.example.com/file")
        file_info = {"FileId": 42, "fileName": "doc.pdf", "Type": 0, "Size": 1024,
                     "Etag": "abc", "S3KeyFlag": ""}
        result = session.get_file_link(file_info)
        assert result.code == 0
        assert result.data == "https://resolved.example.com/file"

    @responses.activate
    def test_get_file_link_network_error(self):
        responses.post(
            "https://www.123pan.cn/a/api/file/download_info",
            body=requests.exceptions.Timeout("request timed out"),
        )
        session = NetSession()
        file_info = {"FileId": 42, "fileName": "doc.pdf", "Type": 0, "Size": 1024,
                     "Etag": "abc", "S3KeyFlag": ""}
        result = session.get_file_link(file_info)
        assert result.code == -1

    @responses.activate
    def test_headers_property_returns_copy(self):
        session = NetSession()
        headers = session.headers
        headers["custom"] = "test"
        assert "custom" not in session._http.headers
