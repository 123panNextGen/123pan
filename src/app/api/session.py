import concurrent.futures
import json
import os
import re
import time
import threading
from pathlib import Path
from typing import Any, Optional, Callable
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

        # 多线程下载配置
        self._multi_thread_enabled: bool = True
        self._num_threads: int = 4
        self._chunk_size: int = 1024 * 1024  # 每个分片 1MB

        # 速度限制器引用（由外部注入）
        self._download_limiter = None
        self._upload_limiter = None

        # 进度回调
        self._progress_callback: Optional[Callable[[int, int], None]] = None

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

    # ---- 多线程 / 速度 / 代理 配置 ----

    def set_multi_thread(self, enabled: bool, num_threads: int = 4):
        """启用或关闭多线程下载。

        Args:
            enabled: 是否启用多线程下载。
            num_threads: 线程数，默认 4。
        """
        self._multi_thread_enabled = enabled
        self._num_threads = max(1, min(num_threads, 16))

    def set_speed_limiter(self, limiter, is_upload: bool = False):
        """设置速度限制器。

        Args:
            limiter: SpeedLimiter 实例。
            is_upload: 是否为上传限速器。
        """
        if is_upload:
            self._upload_limiter = limiter
        else:
            self._download_limiter = limiter

    def set_progress_callback(self, callback: Optional[Callable[[int, int], None]]):
        """设置传输进度回调。

        Args:
            callback: 回调函数 (downloaded_bytes, total_bytes)。
        """
        self._progress_callback = callback

    def set_proxy(self, proxy_url: str):
        """设置代理。

        Args:
            proxy_url: 代理 URL，如 'http://127.0.0.1:8080' 或 'socks5://127.0.0.1:1080'。
                       传空字符串则清除代理。
        """
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        # 清除现有代理适配器
        self._http.adapters.clear()
        self._transfer.adapters.clear()
        if proxy_url:
            # 为带代理的 session 重新挂载适配器
            for session in (self._http, self._transfer):
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=16, pool_maxsize=32
                )
                session.mount("https://", adapter)
                session.mount("http://", adapter)
        else:
            # 恢复无代理状态
            for session in (self._http, self._transfer):
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=16, pool_maxsize=32
                )
                session.mount("https://", adapter)
                session.mount("http://", adapter)
        self._http.proxies = proxies or {}
        self._transfer.proxies = proxies or {}

    def set_proxy_auth(self, proxy_type: str, host: str, port: int,
                       username: str = "", password: str = ""):
        """通过参数设置代理。

        Args:
            proxy_type: 代理类型 'http' 或 'socks5'。
            host: 代理主机。
            port: 代理端口。
            username: 用户名（可选）。
            password: 密码（可选）。
        """
        if not host or port <= 0:
            self.set_proxy("")
            return

        auth = f"{username}:{password}@" if username and password else ""
        proxy_url = f"{proxy_type}://{auth}{host}:{port}"
        self.set_proxy(proxy_url)

    # ---- 多线程下载 ----

    def download_file_multithread(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """多线程分片下载文件。

        先发送 HEAD 请求检查服务器是否支持 Range，
        若支持且文件大于分片阈值则使用多线程，否则回退到单线程。

        Args:
            url: 下载链接。
            file_path: 保存路径。
            file_size: 文件总大小（字节）。
            progress_callback: 进度回调 (downloaded, total)。

        Returns:
            是否下载成功。
        """
        if not self._multi_thread_enabled or self._num_threads <= 1:
            return self._download_single(url, file_path, file_size, progress_callback)

        # 检查服务器是否支持 Range
        supports_range = self._check_range_support(url)
        min_chunk = 5 * 1024 * 1024  # 小于 5MB 不分片

        if not supports_range or file_size < min_chunk:
            return self._download_single(url, file_path, file_size, progress_callback)

        return self._download_chunked(url, file_path, file_size, progress_callback)

    def _check_range_support(self, url: str) -> bool:
        """检查 URL 是否支持 Range 请求。"""
        try:
            resp = self._transfer.head(url, timeout=10, allow_redirects=True)
            return resp.headers.get("Accept-Ranges") == "bytes"
        except requests.RequestException:
            return False

    def _download_single(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """单线程流式下载。"""
        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        try:
            with self._transfer.get(url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                downloaded = 0
                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if self._download_limiter:
                                wait = self._download_limiter.consume(len(chunk))
                                if wait > 0:
                                    time.sleep(wait)
                            if progress_callback:
                                progress_callback(downloaded, file_size)
            if temp_path.exists():
                if file_path.exists():
                    file_path.unlink()
                temp_path.rename(file_path)
            return True
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _download_chunked(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """多线程分片下载。"""
        chunk_size = max(self._chunk_size, file_size // self._num_threads)
        ranges = []
        start = 0
        while start < file_size:
            end = min(start + chunk_size - 1, file_size - 1)
            ranges.append((start, end))
            start = end + 1

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        progress_lock = threading.Lock()
        downloaded_bytes = [0] * len(ranges)

        def _report_progress():
            if progress_callback:
                total = sum(downloaded_bytes)
                progress_callback(total, file_size)

        def _download_chunk(idx: int, byte_range: tuple):
            headers = {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"}
            try:
                with self._transfer.get(
                    url, headers=headers, stream=True, timeout=60
                ) as resp:
                    resp.raise_for_status()
                    chunk_data = bytearray()
                    for data in resp.iter_content(chunk_size=8192):
                        if data:
                            chunk_data.extend(data)
                            if self._download_limiter:
                                wait = self._download_limiter.consume(len(data))
                                if wait > 0:
                                    time.sleep(wait)
                            with progress_lock:
                                downloaded_bytes[idx] += len(data)
                                _report_progress()
                    return bytes(chunk_data), byte_range[0]
            except Exception:
                return None, byte_range[0]

        # 使用线程池并行下载
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._num_threads
        ) as executor:
            futures = {
                executor.submit(_download_chunk, i, r): i
                for i, r in enumerate(ranges)
            }
            results = {}
            for future in concurrent.futures.as_completed(futures):
                data, offset = future.result()
                if data is None:
                    raise RuntimeError(f"分片下载失败: offset={offset}")
                results[offset] = data

        # 按顺序写入文件
        with open(temp_path, "wb") as f:
            for byte_range in ranges:
                f.write(results[byte_range[0]])

        if temp_path.exists():
            if file_path.exists():
                file_path.unlink()
            temp_path.rename(file_path)
        return True

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
