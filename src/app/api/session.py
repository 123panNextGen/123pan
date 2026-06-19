import json
import re
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from .model import (
    ApiCode,
    ApiReturnModel,
    DeviceModel,
    FileItemModel,
    FileListResponse,
    UserInfoModel,
)

BASE_URL = "https://www.123pan.com"


class NetSession:
    """123云盘 HTTP API 会话层，负责所有 HTTP 请求。

    对应 Flutter 项目 pan123next 中的 NetSession。
    """

    def __init__(self):
        self._user_info: Optional[UserInfoModel] = None
        self._http = requests.Session()
        self._http.headers.update({
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "platform": "android",
            "devicename": "Xiaomi",
            "host": "www.123pan.com",
            "app-version": "61",
            "x-app-version": "2.4.0",
        })

        # 传输专用会话：用于下载（CDN）与上传（S3）。
        # 不携带 123pan 鉴权头，并扩大连接池以适配多线程分片传输，
        # 复用 TCP/TLS 连接，避免每个分片都重新握手。
        self._transfer = requests.Session()
        transfer_adapter = requests.adapters.HTTPAdapter(
            pool_connections=16, pool_maxsize=32
        )
        self._transfer.mount("https://", transfer_adapter)
        self._transfer.mount("http://", transfer_adapter)

    @property
    def http(self) -> requests.Session:
        """公开的 requests.Session 实例，供外部直接发起 HTTP 请求。"""
        return self._http

    @property
    def transfer(self) -> requests.Session:
        """传输专用 Session（下载/上传 CDN 与 S3），不携带鉴权头。"""
        return self._transfer

    @property
    def user_info(self) -> Optional[UserInfoModel]:
        return self._user_info

    @property
    def authorization(self) -> str:
        if self._user_info:
            return self._user_info.authorization
        return ""

    @property
    def headers(self) -> dict:
        """返回当前完整的请求头（只读）。"""
        return dict(self._http.headers)

    def set_user_info(self, user_info: UserInfoModel):
        """设置用户信息并刷新请求头。"""
        self._user_info = user_info
        self._update_headers()

    def _build_headers(self) -> dict[str, str]:
        """构建设备伪装请求头。"""
        device = self._user_info.device if self._user_info else None
        headers: dict[str, str] = {}
        if device:
            headers["user-agent"] = f"123pan/v2.4.0({device.os};Xiaomi)"
            headers["osversion"] = device.os
            headers["devicetype"] = device.type
        if self._user_info:
            headers["loginuuid"] = self._user_info.uuid
            if self._user_info.authorization:
                headers["authorization"] = self._user_info.authorization
        return headers

    def _update_headers(self):
        """将伪装请求头合并到 Session 默认头中。"""
        self._http.headers.update(self._build_headers())

    # ---- 账户 ----

    def login(self, user_name: str, password: str) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/b/api/user/sign_in")
        data = {"type": 1, "passport": user_name, "password": password}
        try:
            resp = self._http.post(url, data=data, timeout=(3, 5))
        except requests.RequestException as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        body = resp.json()
        code = body.get("code", -1)
        if code != 200:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        token = body["data"]["token"]
        authorization = "Bearer " + token

        set_cookies = resp.headers.get("Set-Cookie", "")
        cookies: dict[str, Optional[str]] = {}
        for cookie in set_cookies.split(";"):
            if "=" in cookie:
                key, value = cookie.strip().split("=", 1)
                cookies[key] = value
            else:
                cookies[cookie.strip()] = None

        if self._user_info is None:
            self._user_info = UserInfoModel(
                user_name=user_name,
                password=password,
                uuid="",
                authorization=authorization,
                device=DeviceModel(os="", type=""),
            )
        else:
            self._user_info.user_name = user_name
            self._user_info.password = password
            self._user_info.authorization = authorization
        self._update_headers()

        return ApiReturnModel(
            code=200,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data={
                "cookies": cookies,
                "token": token,
                "authorization": authorization,
            },
        )

    # ---- 文件列表 ----

    def get_file_list(
        self,
        file_id: int = 0,
        reverse: bool = False,
        trashed: bool = False,
        page: int = 1,
        limit: int = 100,
        retry_login: bool = True,
    ) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/api/file/list/new")
        params = {
            "driveId": 0,
            "limit": limit,
            "next": 0,
            "orderBy": "file_id",
            "orderDirection": "asc" if reverse else "desc",
            "parentFileId": str(file_id),
            "trashed": str(trashed).lower(),
            "SearchData": "",
            "Page": str(page),
            "OnlyLookAbnormalFile": 0,
        }
        try:
            resp = self._http.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        body = resp.json()
        code = body.get("code", -1)
        if code == 2 and retry_login:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", "token 过期"),
            )
        if code != 0:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        try:
            file_list_response = FileListResponse.from_dict(body)
        except Exception as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=f"解析响应失败: {e}",
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=file_list_response,
        )

    def get_trash_list(self, file_id: int = 0) -> ApiReturnModel:
        return self.get_file_list(file_id=file_id, trashed=True)

    # ---- 文件夹操作 ----

    def create_dir(self, dir_name: str, parent_file_id: int) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/upload_request")
        data = {
            "driveId": 0,
            "etag": "",
            "fileName": dir_name,
            "parentFileId": parent_file_id,
            "size": 0,
            "type": 1,
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }
        try:
            resp = self._http.post(
                url, data=json.dumps(data), timeout=10
            )
        except requests.RequestException as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        body = resp.json()
        code = body.get("code", -1)
        if code != 0:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=body.get("data"),
        )

    # ---- 删除/恢复 ----

    def trash_file(self, file_info: dict | FileItemModel, operation: bool = True) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/trash")
        if isinstance(file_info, FileItemModel):
            payload = file_info.to_json()
        else:
            payload = file_info
        data = {
            "driveId": 0,
            "fileTrashInfoList": payload,
            "operation": operation,
        }
        try:
            resp = self._http.post(
                url, data=json.dumps(data), timeout=10
            )
        except requests.RequestException as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        body = resp.json()
        code = body.get("code", -1)
        if code != 0:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg=body.get("message", ""),
        )

    def restore_file(self, file_info: dict | FileItemModel) -> ApiReturnModel:
        return self.trash_file(file_info, operation=False)

    # ---- 下载链接 ----

    def get_file_link(self, file_info: dict | FileItemModel) -> ApiReturnModel:  # pylint: disable=protected-access
        if isinstance(file_info, FileItemModel):
            type_val = file_info._type  # pylint: disable=protected-access
        else:
            type_val = file_info.get("Type", file_info.get("type", 0))

        request_data: dict[str, Any]
        if type_val == 1:
            url = urljoin(BASE_URL, "/a/api/file/batch_download_info")
            if isinstance(file_info, FileItemModel):
                file_id = file_info.file_id
            else:
                file_id = int(file_info.get("FileId", file_info.get("fileId", 0)))
            request_data = {"fileIdList": [{"fileId": file_id}]}
        else:
            url = urljoin(BASE_URL, "/a/api/file/download_info")
            if isinstance(file_info, FileItemModel):
                request_data = {
                    "driveId": 0,
                    "etag": file_info.etag,
                    "fileId": file_info.file_id,
                    "s3keyFlag": file_info.s3key_flag,
                    "type": file_info._type,  # pylint: disable=protected-access
                    "fileName": file_info.file_name,
                    "size": file_info.size,
                }
            else:
                request_data = {
                    "driveId": 0,
                    "etag": file_info.get("Etag", file_info.get("etag", "")),
                    "fileId": file_info.get("FileId", file_info.get("fileId", 0)),
                    "s3keyFlag": file_info.get("S3KeyFlag", file_info.get("s3keyFlag", "")),
                    "type": file_info.get("Type", file_info.get("type", 0)),
                    "fileName": file_info.get("FileName", file_info.get("fileName", "")),
                    "size": file_info.get("Size", file_info.get("size", 0)),
                }
        try:
            resp = self._http.post(
                url, data=json.dumps(request_data), timeout=10
            )
        except requests.RequestException as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        body = resp.json()
        code = body.get("code", -1)
        if code != 0:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        download_url = body["data"]["DownloadUrl"]
        redirect_url = self._resolve_download_url(download_url)
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=redirect_url,
        )

    def _resolve_download_url(self, url: str) -> str:
        """解析 302 重定向获取真实下载链接。

        对应 Flutter 中用 dart:io HttpClient 手动跟随重定向的逻辑。
        """
        try:
            resp = self._transfer.get(url, timeout=10, allow_redirects=False)
            text = resp.text
            url_pattern = re.compile(r"href='(https?://[^']+)'")
            match = url_pattern.search(text)
            if match:
                return match.group(1)
        except requests.RequestException:
            pass
        return url

    # ---- 重命名 ----

    def rename_file(self, file_id: int, new_name: str) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/rename")
        data = {"driveId": 0, "fileId": file_id, "fileName": new_name}
        try:
            resp = self._http.post(
                url, data=json.dumps(data), timeout=10
            )
        except requests.RequestException as e:
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        body = resp.json()
        code = body.get("code", -1)
        if code != 0:
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
        )
