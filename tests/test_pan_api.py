"""测试 Pan123 API 业务方法（login, get_dir, delete, rename, share, mkdir 等）"""
import json
import threading
import time
from unittest.mock import patch, MagicMock, call

import pytest
import requests

from src.app.common.api import Pan123, RateLimitError, UPLOAD_PART_SIZE
from src.app.view.transfer_interface import UploadThread


def _mock_response(status_code=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {"code": 0, "message": "success"}
    resp.headers = headers or {}
    return resp


@pytest.fixture
def pan():
    """创建 Pan123 实例，跳过 __init__ 中的网络请求"""
    with patch.object(Pan123, "__init__", lambda self, **kw: None):
        p = Pan123()
        p.user_name = "testuser"
        p.password = "testpwd"
        p.authorization = "Bearer token123"
        p.devicetype = "MI5"
        p.osversion = "Android_12"
        p.loginuuid = "abc123"
        p.cookies = None
        p.recycle_list = None
        p.list = []
        p.total = 0
        p.parent_file_name_list = []
        p.all_file = False
        p.file_page = 0
        p.file_list = []
        p.dir_list = []
        p.name_dict = {}
        p.parent_file_id = 0
        p.parent_file_list = [0]
        p._login_lock = threading.Lock()

        # 创建带重试的 session（和 Pan123.__init__ 一致）
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry = Retry(total=3, backoff_factor=0.5, allowed_methods=["GET", "POST", "PUT", "HEAD"], raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry)
        p.session = requests.Session()
        p.session.mount("https://", adapter)
        p.session.mount("http://", adapter)

        p.header_logined = {
            "user-agent": "123pan/v2.4.0(Android_12;Xiaomi)",
            "authorization": p.authorization,
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "osversion": p.osversion,
            "loginuuid": p.loginuuid,
            "platform": "android",
            "devicetype": p.devicetype,
            "devicename": "Xiaomi",
            "host": "www.123pan.com",
            "app-version": "61",
            "x-app-version": "2.4.0",
        }
        return p


class TestLogin:
    def test_login_success(self, pan):
        login_resp = _mock_response(200, {"code": 200, "data": {"token": "newtoken"}, "message": "ok"})
        login_resp.headers = {"Set-Cookie": "sid=abc123; Path=/"}

        with patch.object(pan.session, "post", return_value=login_resp) as mock_post, \
             patch.object(pan, "save_file"):
            code = pan.login()
            assert code == 200
            assert pan.authorization == "Bearer newtoken"
            assert pan.cookies["sid"] == "abc123"

    def test_login_wrong_password(self, pan):
        login_resp = _mock_response(200, {"code": 4001, "message": "密码错误"})

        with patch.object(pan.session, "post", return_value=login_resp):
            code = pan.login()
            assert code == 4001

    def test_login_network_error(self, pan):
        with patch.object(pan.session, "post", side_effect=requests.exceptions.ConnectionError("连接失败")):
            with pytest.raises(requests.exceptions.ConnectionError):
                pan.login()


class TestGetDir:
    def test_get_dir_success(self, pan):
        resp = _mock_response(200, {
            "code": 0, "message": "ok",
            "data": {"Total": 2, "InfoList": [
                {"FileName": "a.txt", "FileId": 1},
                {"FileName": "b.txt", "FileId": 2},
            ]}
        })

        with patch.object(pan.session, "get", return_value=resp):
            code, items = pan.get_dir_by_id(0)
            assert code == 0
            assert len(items) == 2

    def test_get_dir_empty(self, pan):
        resp = _mock_response(200, {
            "code": 0, "data": {"Total": 0, "InfoList": []}
        })

        with patch.object(pan.session, "get", return_value=resp):
            code, items = pan.get_dir_by_id(0)
            assert code == 0
            assert items == []

    def test_get_dir_server_error(self, pan):
        resp = _mock_response(200, {"code": -1, "message": "内部错误"})

        with patch.object(pan.session, "get", return_value=resp):
            code, items = pan.get_dir_by_id(0)
            assert code == -1
            assert items == []

    def test_get_dir_network_timeout(self, pan):
        with patch.object(pan.session, "get", side_effect=requests.exceptions.Timeout("超时")):
            code, items = pan.get_dir_by_id(0)
            assert code == -1
            assert items == []

    def test_get_dir_by_id_no_side_effects(self, pan):
        pan.file_page = 7
        pan.total = 99
        pan.all_file = True
        pan.list = [{"FileId": 1}]
        resp = _mock_response(
            200,
            {"code": 0, "data": {"Total": 1, "InfoList": [{"FileId": 2}]}}
        )

        with patch.object(pan.session, "get", return_value=resp):
            code, items = pan.get_dir_by_id(123, save=False)

        assert code == 0
        assert items == [{"FileId": 2}]
        assert pan.file_page == 7
        assert pan.total == 99
        assert pan.all_file is True
        assert pan.list == [{"FileId": 1}]

    def test_get_dir_by_id_save_true_updates_shared_state(self, pan):
        resp = _mock_response(
            200,
            {"code": 0, "data": {"Total": 1, "InfoList": [{"FileId": 2}]}}
        )

        with patch.object(pan.session, "get", return_value=resp):
            code, items = pan.get_dir_by_id(123, save=True)

        assert code == 0
        assert items == [{"FileId": 2}]
        assert pan.file_page == 1
        assert pan.total == 1
        assert pan.all_file is True
        assert pan.list == [{"FileId": 2}]


class TestTokenRefresh:
    def test_auto_refresh_on_code_2(self, pan):
        expired = _mock_response(200, {"code": 2, "message": "expired"})
        success = _mock_response(200, {"code": 0, "message": "ok"})

        def fake_login():
            pan.authorization = "Bearer refreshed"
            pan.header_logined["authorization"] = pan.authorization
            return 200

        with patch.object(pan.session, "get", side_effect=[expired, success]) as mock_get, \
             patch.object(pan, "_login_without_lock", side_effect=fake_login) as mock_login:
            response = pan._api_request(
                pan.session.get,
                "https://example.com/list",
                headers=pan.header_logined.copy(),
            )

        assert response is success
        assert mock_login.call_count == 1
        assert mock_get.call_args_list[1].kwargs["headers"]["authorization"] == "Bearer refreshed"

    def test_max_one_refresh(self, pan):
        expired = _mock_response(200, {"code": 2, "message": "expired"})

        with patch.object(pan.session, "get", side_effect=[expired, expired]) as mock_get, \
             patch.object(pan, "_login_without_lock", return_value=200) as mock_login:
            response = pan._api_request(
                pan.session.get,
                "https://example.com/list",
                headers=pan.header_logined.copy(),
            )

        assert response is expired
        assert mock_get.call_count == 2
        assert mock_login.call_count == 1

    def test_login_failure_raises(self, pan):
        expired = _mock_response(200, {"code": 2, "message": "expired"})

        with patch.object(pan.session, "get", return_value=expired), \
             patch.object(pan, "_login_without_lock", return_value=4001):
            with pytest.raises(RuntimeError, match="token 刷新失败"):
                pan._api_request(
                    pan.session.get,
                    "https://example.com/list",
                    headers=pan.header_logined.copy(),
                )

    def test_non_json_response_returns_raw(self, pan):
        response = MagicMock()
        response.json.side_effect = json.decoder.JSONDecodeError("bad", "", 0)

        with patch.object(pan.session, "get", return_value=response):
            result = pan._api_request(
                pan.session.get,
                "https://example.com/raw",
                headers=pan.header_logined.copy(),
            )

        assert result is response

    def test_login_lock_prevents_concurrent_refresh(self, pan):
        results = []
        login_calls = 0

        def fake_get(_url, **kwargs):
            auth = kwargs["headers"]["authorization"]
            code = 2 if auth == "Bearer token123" else 0
            return _mock_response(200, {"code": code, "message": "ok"})

        def fake_login():
            nonlocal login_calls
            login_calls += 1
            time.sleep(0.05)
            pan.authorization = "Bearer refreshed"
            pan.header_logined["authorization"] = pan.authorization
            return 200

        def call_api():
            response = pan._api_request(
                pan.session.get,
                "https://example.com/list",
                headers=pan.header_logined.copy(),
            )
            results.append(response.json()["code"])

        with patch.object(pan.session, "get", side_effect=fake_get), \
             patch.object(pan, "_login_without_lock", side_effect=fake_login):
            threads = [threading.Thread(target=call_api) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        assert sorted(results) == [0, 0]
        assert login_calls == 1

    def test_normal_code_passes_through(self, pan):
        success = _mock_response(200, {"code": 0, "message": "ok"})

        with patch.object(pan.session, "get", return_value=success), \
             patch.object(pan, "_login_without_lock") as mock_login:
            response = pan._api_request(
                pan.session.get,
                "https://example.com/list",
                headers=pan.header_logined.copy(),
            )

        assert response is success
        mock_login.assert_not_called()


class TestRename:
    def test_rename_success(self, pan):
        resp = _mock_response(200, {"code": 0, "message": "ok"})

        with patch.object(pan.session, "post", return_value=resp) as mock_post:
            result = pan.rename_file(123, "new_name.txt")
            assert result is True
            args, kwargs = mock_post.call_args
            assert "rename" in args[0]
            assert json.loads(kwargs["data"])["fileName"] == "new_name.txt"

    def test_rename_failure(self, pan):
        resp = _mock_response(200, {"code": -1, "message": "文件名已存在"})

        with patch.object(pan.session, "post", return_value=resp):
            result = pan.rename_file(123, "dup.txt")
            assert result is False


class TestShare:
    def test_share_success(self, pan):
        resp = _mock_response(200, {"code": 0, "data": {"ShareKey": "abc123"}, "message": "ok"})

        with patch.object(pan.session, "post", return_value=resp):
            url = pan.share([1, 2, 3])
            assert "abc123" in url

    def test_share_failure(self, pan):
        resp = _mock_response(200, {"code": -1, "message": "分享失败"})

        with patch.object(pan.session, "post", return_value=resp):
            with pytest.raises(RuntimeError, match="分享失败"):
                pan.share([1])

    def test_share_empty_list(self, pan):
        with pytest.raises(ValueError, match="文件ID列表为空"):
            pan.share([])


class TestDeleteFile:
    def test_delete_by_num(self, pan):
        pan.list = [{"FileName": "a.txt", "FileId": 1, "Type": 0, "Size": 100, "Etag": "x", "S3KeyFlag": "y"}]
        resp = _mock_response(200, {"code": 0, "message": "ok"})

        with patch.object(pan.session, "post", return_value=resp) as mock_post:
            pan.delete_file(0)
            mock_post.assert_called_once()

    def test_delete_invalid_num(self, pan):
        with pytest.raises(IndexError):
            pan.delete_file(999)

    def test_delete_non_digit_string(self, pan):
        with pytest.raises(ValueError):
            pan.delete_file("abc")

    def test_delete_accepts_detail_dict_without_shared_list(self, pan):
        file_detail = {"FileId": 1, "Type": 0, "FileName": "a.txt"}
        resp = _mock_response(200, {"code": 0, "message": "ok"})

        with patch.object(pan.session, "post", return_value=resp) as mock_post:
            pan.delete_file(file_detail, by_num=False)

        mock_post.assert_called_once()


class TestMkdir:
    def test_mkdir_new_folder(self, pan):
        pan.list = []
        resp = _mock_response(200, {
            "code": 0, "data": {"FileId": 42, "Info": {"FileId": 42}}, "message": "ok"
        })

        with patch.object(pan.session, "post", return_value=resp):
            result = pan.mkdir("new_folder")
            assert result == 42

    def test_mkdir_existing_folder(self, pan):
        pan.list = [{"FileName": "existing", "FileId": 10, "Type": 1}]

        result = pan.mkdir("existing")
        assert result == 10

    def test_mkdir_api_failure(self, pan):
        pan.list = []
        resp = _mock_response(200, {"code": -1, "message": "创建失败"})

        with patch.object(pan.session, "post", return_value=resp):
            with pytest.raises(RuntimeError, match="创建目录 'fail_folder' 失败"):
                pan.mkdir("fail_folder")


class TestFolderUploadPlan:
    def test_choose_available_directory_name_appends_suffix(self, pan):
        name = pan._choose_available_directory_name(
            {"资料", "资料(1)"},
            "资料",
        )

        assert name == "资料(2)"

    def test_ensure_directory_reuses_existing_child(self, pan):
        with patch.object(
            pan,
            "_get_child_directory_map",
            return_value={"docs": 99},
        ), patch.object(pan, "_create_directory") as mock_create:
            result = pan.ensure_directory(0, "docs")

        assert result == 99
        mock_create.assert_not_called()

    def test_prepare_folder_upload_creates_remote_tree(self, pan, tmp_path):
        root = tmp_path / "资料"
        child = root / "子目录"
        child.mkdir(parents=True)
        (root / "a.txt").write_text("a", encoding="utf-8")
        (child / "b.txt").write_text("bb", encoding="utf-8")

        created = []
        next_id = 100

        def fake_create(parent_id, dirname):
            nonlocal next_id
            next_id += 1
            created.append((parent_id, dirname))
            return next_id

        def fake_dir_map(parent_id):
            if parent_id == 0:
                return {"资料": 7}
            return {}

        with patch.object(
            pan,
            "_get_child_directory_map",
            side_effect=fake_dir_map,
        ), patch.object(
            pan,
            "_create_directory_with_backoff",
            side_effect=fake_create,
        ):
            plan = pan.prepare_folder_upload(root, 0)

        assert created == [(0, "资料(1)"), (101, "子目录")]
        assert plan["root_dir_name"] == "资料(1)"
        assert plan["root_dir_id"] == 101
        assert plan["created_dir_count"] == 2
        assert plan["file_targets"] == [
            {
                "file_name": "a.txt",
                "file_size": 1,
                "local_path": str(root / "a.txt"),
                "target_dir_id": 101,
            },
            {
                "file_name": "b.txt",
                "file_size": 2,
                "local_path": str(child / "b.txt"),
                "target_dir_id": 102,
            },
        ]


class TestCreateDirectory:
    def test_429_backoff_retries(self, pan):
        with patch.object(
            pan,
            "_create_directory",
            side_effect=[RateLimitError("429"), "dir_id_123"],
        ) as mock_create, patch("src.app.common.api.time.sleep") as mock_sleep:
            result = pan._create_directory_with_backoff(0, "docs")

        assert result == "dir_id_123"
        assert mock_create.call_count == 2
        mock_sleep.assert_called_once_with(1.0)

    def test_429_exponential_backoff_timing(self, pan):
        with patch.object(
            pan,
            "_create_directory",
            side_effect=[
                RateLimitError("429"),
                RateLimitError("429"),
                RateLimitError("429"),
                "dir_id_123",
            ],
        ), patch("src.app.common.api.time.sleep") as mock_sleep:
            result = pan._create_directory_with_backoff(0, "docs")

        assert result == "dir_id_123"
        assert [call.args[0] for call in mock_sleep.call_args_list] == [1.0, 2.0, 4.0]

    def test_429_max_backoff_cap(self, pan):
        side_effect = [RateLimitError("429")] * 6 + ["dir_id_123"]

        with patch.object(pan, "_create_directory", side_effect=side_effect), \
             patch("src.app.common.api.time.sleep") as mock_sleep:
            result = pan._create_directory_with_backoff(0, "docs")

        assert result == "dir_id_123"
        assert max(call.args[0] for call in mock_sleep.call_args_list) <= 30.0

    def test_429_max_retries_exhausted(self, pan):
        side_effect = [RateLimitError("429")] * 11

        with patch.object(pan, "_create_directory", side_effect=side_effect), \
             patch("src.app.common.api.time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError, match="已重试 10 次"):
                pan._create_directory_with_backoff(0, "docs")

        assert len(mock_sleep.call_args_list) == 10

    def test_success_no_backoff(self, pan):
        with patch.object(pan, "_create_directory", return_value="dir_id_123"), \
             patch("src.app.common.api.time.sleep") as mock_sleep:
            result = pan._create_directory_with_backoff(0, "docs")

        assert result == "dir_id_123"
        mock_sleep.assert_not_called()

    def test_api_error_raises(self, pan):
        with patch.object(
            pan,
            "_create_directory",
            side_effect=RuntimeError("创建失败"),
        ), patch("src.app.common.api.time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError, match="创建失败"):
                pan._create_directory_with_backoff(0, "docs")

        mock_sleep.assert_not_called()

    def test_prepare_folder_upload_uses_backoff(self, pan, tmp_path):
        root = tmp_path / "资料"
        root.mkdir()
        (root / "a.txt").write_text("a", encoding="utf-8")

        with patch.object(pan, "_get_child_directory_map", return_value={}), \
             patch.object(
                 pan,
                 "_create_directory_with_backoff",
                 return_value=101,
             ) as mock_create:
            plan = pan.prepare_folder_upload(root, 0)

        assert plan["root_dir_id"] == 101
        mock_create.assert_called_once_with(0, "资料")


class TestUploadFileStream:
    def test_parent_id_parameter(self, pan, tmp_path):
        local_file = tmp_path / "demo.txt"
        local_file.write_text("demo", encoding="utf-8")
        request_payloads = []
        response = _mock_response(200, {"code": 0, "data": {"Reuse": True}})

        def fake_post(_url, **kwargs):
            request_payloads.append(kwargs["data"])
            return response

        with patch.object(pan.session, "post", side_effect=fake_post):
            result = pan.upload_file_stream(str(local_file), parent_id=999)

        assert result == "复用上传成功"
        assert request_payloads[0]["parentFileId"] == 999

    def test_parent_id_default_zero(self, pan, tmp_path):
        local_file = tmp_path / "demo.txt"
        local_file.write_text("demo", encoding="utf-8")
        request_payloads = []
        response = _mock_response(200, {"code": 0, "data": {"Reuse": True}})

        def fake_post(_url, **kwargs):
            request_payloads.append(kwargs["data"])
            return response

        with patch.object(pan.session, "post", side_effect=fake_post):
            result = pan.upload_file_stream(str(local_file))

        assert result == "复用上传成功"
        assert request_payloads[0]["parentFileId"] == 0

    def test_new_upload_uses_five_mb_part_size(self, pan, tmp_path):
        local_file = tmp_path / "demo.txt"
        local_file.write_text("demo", encoding="utf-8")
        signal_payloads = []

        class _Signal:
            def emit(self, value):
                signal_payloads.append(value)

        class _Signals:
            progress = _Signal()
            session_info = _Signal()

        upload_res = _mock_response(
            200,
            {
                "code": 0,
                "data": {
                    "Reuse": False,
                    "Bucket": "bucket",
                    "StorageNode": "node",
                    "Key": "key",
                    "UploadId": "upload-id",
                    "FileId": 123,
                },
            },
        )
        init_res = _mock_response(200, {"code": 0, "message": "ok"})
        get_link_res = _mock_response(
            200,
            {
                "code": 0,
                "data": {"presignedUrls": {"1": "https://upload.example/1"}},
            },
        )
        ok_res = _mock_response(200, {"code": 0, "message": "ok"})
        put_res = MagicMock()
        put_res.status_code = 200
        put_res.headers = {"ETag": '"etag-1"'}
        put_res.raise_for_status.return_value = None

        with patch.object(
            pan,
            "_api_request",
            side_effect=[upload_res, init_res, get_link_res, ok_res, ok_res, ok_res],
        ), patch("src.app.common.api.requests.put", return_value=put_res), \
             patch("src.app.common.api.Database.instance") as mock_db:
            mock_db.return_value.get_config.return_value = 1
            pan.upload_file_stream(str(local_file), parent_id=999, signals=_Signals())

        assert signal_payloads[0]["block_size"] == UPLOAD_PART_SIZE


class TestThreadSafety:
    def test_upload_thread_no_parent_file_id_mutation(self):
        task = MagicMock()
        task.local_path = "/tmp/demo.txt"
        task.target_dir_id = 456
        task.speed_tracker = None
        task.db_task_id = None
        task.bucket = ""
        task.upload_key = ""
        task.upload_id_s3 = ""
        task.is_cancelled = False
        task.pause_requested = False
        pan = MagicMock()
        pan.parent_file_id = 123
        pan.upload_file_stream.return_value = "复用上传成功"

        UploadThread(task, pan).run()

        assert pan.parent_file_id == 123
        assert pan.upload_file_stream.call_args.kwargs["parent_id"] == 456


class TestRecycle:
    def test_recycle_success(self, pan):
        resp = _mock_response(200, {
            "code": 0, "data": {"InfoList": [{"FileId": 1}, {"FileId": 2}]}, "message": "ok"
        })

        with patch.object(pan.session, "get", return_value=resp):
            pan.recycle()
            assert len(pan.recycle_list) == 2
