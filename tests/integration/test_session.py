"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import io
import json

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

    @responses.activate
    def test_set_client_simulation(self):
        responses.post(
            "https://www.123pan.cn/b/api/user/sign_in",
            json={"code": 200, "data": {"token": "test_token"}},
            status=200,
        )
        session = NetSession()
        session.login("test_user", "test_pass")
        assert session.headers["platform"] == "android"

        session.set_client_simulation(False)
        assert session.headers["platform"] == "web"
        assert session.headers["app-version"] == "3"
        assert "devicename" not in session.headers
        assert "x-app-version" not in session.headers
        assert "osversion" not in session.headers
        assert "devicetype" not in session.headers
        assert not session.headers.get("user-agent", "").startswith("123pan/")
        assert session.headers["content-type"] == "application/json"
        assert session.headers["authorization"] == "Bearer test_token"
        assert "loginuuid" in session.headers

        session.set_client_simulation(True)
        assert session.headers["platform"] == "android"
        assert session.headers["devicename"] == "Xiaomi"
        assert "osversion" in session.headers
        assert "devicetype" in session.headers

    def test_set_error_backoff_retry(self):
        session = NetSession()
        assert session._error_backoff_retry_enabled is True

        session.set_error_backoff_retry(False)
        assert session._error_backoff_retry_enabled is False

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
    def test_login_falls_back_after_network_error(self):
        responses.post(
            "https://www.123pan.cn/b/api/user/sign_in",
            body=requests.exceptions.SSLError("wrong version number"),
        )
        responses.post(
            "https://api.123278.com/b/api/user/sign_in",
            json={"code": 200, "data": {"token": "test_token"}},
            status=200,
        )
        responses.get(
            "https://api.123278.com/api/ping",
            json={"ok": True},
            status=200,
        )

        session = NetSession()
        result = session.login("test_user", "test_pass")
        follow_up = session.http.get("https://www.123pan.cn/api/ping")

        assert result.code == 200
        assert follow_up.json() == {"ok": True}
        assert [call.request.url for call in responses.calls] == [
            "https://www.123pan.cn/b/api/user/sign_in",
            "https://api.123278.com/b/api/user/sign_in",
            "https://api.123278.com/api/ping",
        ]

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
        responses.post(
            "https://api.123278.com/b/api/user/sign_in",
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
        # 拆分后下载 URL 解析为模块级函数（见 api/session_file.py / download_url.py）
        mocker.patch(
            "src.app.api.session_file.resolve_download_url",
            return_value="https://resolved.example.com/file",
        )
        file_info = {"FileId": 42, "fileName": "doc.pdf", "Type": 0, "Size": 1024,
                     "Etag": "abc", "S3KeyFlag": ""}
        result = session.get_file_link(file_info)
        assert result.code == 0
        assert result.data == "https://resolved.example.com/file"

    @responses.activate
    def test_check_download_traffic(self):
        responses.post(
            "https://www.123pan.cn/b/api/file/download/traffic/check",
            json={
                "code": 0,
                "data": {
                    "originalRemainTraffic": 5 * 1024**3,
                    "originalFileSize": 1024**3,
                    "clientFileSize": 512 * 1024**2,
                    "isTrafficExceeded": False,
                    "isBlocked": False,
                },
            },
            status=200,
        )
        session = NetSession()
        result = session.check_download_traffic([42, 43])

        assert result.code == 0
        assert result.data["originalRemainTraffic"] == 5 * 1024**3
        assert json.loads(responses.calls[0].request.body) == {"fids": [42, 43]}

    @responses.activate
    def test_check_download_traffic_api_error(self):
        responses.post(
            "https://www.123pan.cn/b/api/file/download/traffic/check",
            json={"code": 401, "message": "cookie token is empty"},
            status=200,
        )
        session = NetSession()
        result = session.check_download_traffic([42])

        assert result.code == 401
        assert result.msg == "cookie token is empty"

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


class TestDownloadResume:
    @responses.activate
    def test_download_single_resume(self, tmp_path):
        session = NetSession()
        file_path = tmp_path / "test.bin"
        temp_path = file_path.with_suffix(".bin.tmp")
        temp_path.write_bytes(b"PARTIAL" * 100)  # 600 字节
        partial_size = temp_path.stat().st_size

        remaining = b"REST" * 100
        responses.get(
            "https://cdn.example.com/test.bin",
            body=remaining,
            status=206,
            headers={"Content-Type": "application/octet-stream"},
        )

        reported = {}

        def cb(d, t):
            reported["d"] = d
            reported["t"] = t

        total = partial_size + len(remaining)
        ok = session._download_single(
            "https://cdn.example.com/test.bin", file_path, total, cb
        )
        assert ok is True
        assert file_path.read_bytes() == b"PARTIAL" * 100 + remaining
        assert reported["t"] == total
        assert reported["d"] == total
        # 验证发送了 Range 头
        sent = responses.calls[0].request
        assert sent.headers.get("Range") == f"bytes={partial_size}-"
        # 临时文件应已改名
        assert not temp_path.exists()

    @responses.activate
    def test_download_single_fresh(self, tmp_path):
        """无部分文件时全量下载（wb 模式，无 Range）。"""
        session = NetSession()
        file_path = tmp_path / "fresh.bin"
        body = b"FRESH" * 50
        responses.get(
            "https://cdn.example.com/fresh.bin",
            body=body,
            status=200,
            headers={"Content-Type": "application/octet-stream"},
        )
        ok = session._download_single(
            "https://cdn.example.com/fresh.bin", file_path, len(body)
        )
        assert ok is True
        assert file_path.read_bytes() == body
        sent = responses.calls[0].request
        assert sent.headers.get("Range") is None

    @responses.activate
    def test_download_multithread_resume_falls_back_single(self, tmp_path):
        """有续传偏移时走单线程续传。"""
        session = NetSession()
        file_path = tmp_path / "mt.bin"
        temp_path = file_path.with_suffix(".bin.tmp")
        temp_path.write_bytes(b"X" * 100)
        partial_size = 100

        remaining = b"Y" * 50
        responses.get(
            "https://cdn.example.com/mt.bin",
            body=remaining,
            status=206,
            headers={"Content-Type": "application/octet-stream"},
        )
        ok = session.download_file_multithread(
            "https://cdn.example.com/mt.bin", file_path, 150, resume_offset=partial_size
        )
        assert ok is True
        assert file_path.read_bytes() == b"X" * 100 + b"Y" * 50
        sent = responses.calls[0].request
        assert sent.headers.get("Range") == "bytes=100-"


class TestNetSessionModPid:
    @responses.activate
    def test_mod_pid_success(self):
        responses.post(
            "https://www.123pan.cn/b/api/file/mod_pid",
            json={"code": 0, "message": ""},
            status=200,
        )
        session = NetSession()
        result = session.mod_pid([1, 2], 99)
        assert result.code == 0
        assert result.api_code_enum == ApiCode.success
        # 验证请求体
        sent = responses.calls[0].request
        import json as _json
        body = _json.loads(sent.body)
        assert body["parentFileId"] == 99
        assert body["fileIdList"] == [{"FileId": 1}, {"FileId": 2}]

    @responses.activate
    def test_mod_pid_failure(self):
        responses.post(
            "https://www.123pan.cn/b/api/file/mod_pid",
            json={"code": 403, "message": "无权限"},
            status=200,
        )
        session = NetSession()
        result = session.mod_pid([1], 99)
        assert result.code == 403
        assert result.api_code_enum == ApiCode.fail
        assert result.msg == "无权限"

    @responses.activate
    def test_mod_pid_network_error(self):
        responses.post(
            "https://www.123pan.cn/b/api/file/mod_pid",
            body=requests.exceptions.ConnectionError("connection refused"),
        )
        responses.post(
            "https://api.123278.com/b/api/file/mod_pid",
            body=requests.exceptions.ConnectionError("connection refused"),
        )
        session = NetSession()
        result = session.mod_pid([1], 99)
        assert result.code == -1
        assert result.api_code_enum == ApiCode.fail


class TestNetSessionCopyFiles:
    @responses.activate
    def test_copy_files_async_success(self):
        responses.post(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/async",
            json={"code": 0, "message": "ok", "data": {"taskId": 1475675}},
            status=200,
        )
        session = NetSession()
        file_list = [{"FileId": 1, "FileName": "a.txt", "Type": 0, "DriveId": 0}]
        result = session.copy_files_async(file_list, 99)
        assert result.code == 0
        assert result.api_code_enum == ApiCode.success
        assert result.data == 1475675
        import json as _json

        body = _json.loads(responses.calls[0].request.body)
        assert body["targetFileId"] == 99
        assert body["fileList"] == file_list

    @responses.activate
    def test_copy_files_async_taskID_uppercase(self):
        """兼容响应字段为 taskID（大写）的情况。"""
        responses.post(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/async",
            json={"code": 0, "message": "ok", "data": {"taskID": "abc123"}},
            status=200,
        )
        session = NetSession()
        result = session.copy_files_async([{"FileId": 1}], 0)
        assert result.code == 0
        assert result.data == "abc123"

    @responses.activate
    def test_copy_files_async_failure(self):
        responses.post(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/async",
            json={"code": 5066, "message": "文件不存在"},
            status=200,
        )
        session = NetSession()
        result = session.copy_files_async([{"FileId": 999}], 99)
        assert result.code == 5066
        assert result.api_code_enum == ApiCode.fail
        assert result.msg == "文件不存在"

    @responses.activate
    def test_copy_files_async_missing_task_id(self):
        responses.post(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/async",
            json={"code": 0, "message": "ok", "data": {}},
            status=200,
        )
        session = NetSession()
        result = session.copy_files_async([{"FileId": 1}], 99)
        assert result.code == -1
        assert "任务" in result.msg

    @responses.activate
    def test_copy_files_async_network_error(self):
        responses.post(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/async",
            body=requests.exceptions.Timeout("request timed out"),
        )
        session = NetSession()
        result = session.copy_files_async([{"FileId": 1}], 99)
        assert result.code == -1
        assert result.api_code_enum == ApiCode.fail

    @responses.activate
    def test_copy_file_task_success(self):
        responses.get(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/task",
            json={"code": 0, "message": "ok", "data": {"status": 2, "failMsg": ""}},
            status=200,
        )
        session = NetSession()
        result = session.copy_file_task(1475675)
        assert result.code == 0
        assert result.data["status"] == 2
        assert "taskId=1475675" in responses.calls[0].request.url

    @responses.activate
    def test_copy_file_task_failure(self):
        responses.get(
            "https://www.123pan.cn/b/api/restful/goapi/v1/file/copy/task",
            json={"code": 429, "message": "请求过于频繁"},
            status=200,
        )
        session = NetSession()
        result = session.copy_file_task(1)
        assert result.code == 429
        assert result.api_code_enum == ApiCode.fail
        assert result.msg == "请求过于频繁"


class TestNetSessionTrash:
    """删除/恢复（trash_file）请求格式回归测试。

    服务器仅接受 fileTrashInfoList 为 [{"FileId": X}] 列表；
    传完整文件信息 dict 时服务器返回 code=0 但静默忽略（文件不会被删除）。
    """

    TRASH_URL = "https://www.123pan.cn/a/api/file/trash"

    def _assert_body(self):
        import json as _json

        body = _json.loads(responses.calls[0].request.body)
        assert body["driveId"] == 0
        assert body["operation"] is True
        assert body["fileTrashInfoList"] == [{"FileId": 123}]

    @responses.activate
    def test_trash_file_dict_extracts_fileid(self):
        """传完整文件 dict 时，请求体只发送 [{"FileId": X}]。"""
        responses.post(
            self.TRASH_URL,
            json={"code": 0, "message": "ok",
                  "data": {"InfoList": [{"FileId": 123}], "AbnormalFileIdList": None}},
            status=200,
        )
        session = NetSession()
        result = session.trash_file({
            "FileId": 123, "FileName": "a.txt", "Size": 10,
            "S3KeyFlag": "x", "Type": 0, "Etag": "e", "ParentFileId": 0,
        })
        assert result.code == 0
        self._assert_body()

    @responses.activate
    def test_trash_file_model_extracts_fileid(self):
        """传 FileItemModel 时同样只发送 [{"FileId": X}]。"""
        responses.post(
            self.TRASH_URL,
            json={"code": 0, "message": "ok",
                  "data": {"InfoList": [{"FileId": 456}], "AbnormalFileIdList": None}},
            status=200,
        )
        from src.app.api.model import FileItemModel

        model = FileItemModel.from_dict({
            "FileId": 456, "FileName": "b.txt", "Type": 0, "Size": 5,
            "Etag": "", "S3KeyFlag": "", "ParentFileId": 0,
        })
        session = NetSession()
        result = session.trash_file(model)
        assert result.code == 0

        import json as _json
        body = _json.loads(responses.calls[0].request.body)
        assert body["fileTrashInfoList"] == [{"FileId": 456}]
        assert body["operation"] is True

    @responses.activate
    def test_trash_file_restore_operation_false(self):
        """恢复操作 operation=False 透传。"""
        responses.post(
            self.TRASH_URL,
            json={"code": 0, "message": "ok",
                  "data": {"InfoList": [{"FileId": 789}], "AbnormalFileIdList": None}},
            status=200,
        )
        session = NetSession()
        result = session.trash_file({"FileId": 789, "FileName": "c.txt"},
                                    operation=False)
        assert result.code == 0

        import json as _json
        body = _json.loads(responses.calls[0].request.body)
        assert body["fileTrashInfoList"] == [{"FileId": 789}]
        assert body["operation"] is False

    @responses.activate
    def test_trash_file_missing_fileid(self):
        """缺少 FileId 时返回错误，不发起请求。"""
        session = NetSession()
        result = session.trash_file({"FileName": "no_id.txt"})
        assert result.code == -1
        assert "FileId" in result.msg
        assert len(responses.calls) == 0

    @responses.activate
    def test_trash_file_server_error(self):
        """服务器返回错误码时透传 message。"""
        responses.post(
            self.TRASH_URL,
            json={"code": 4000, "message": "参数错误"},
            status=200,
        )
        session = NetSession()
        result = session.trash_file({"FileId": 1})
        assert result.code == 4000
        assert result.api_code_enum == ApiCode.fail
        assert result.msg == "参数错误"
