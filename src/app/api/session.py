"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import logging
import time
from typing import Any, Optional, Callable
from urllib.parse import urljoin, urlparse

import requests

from .constants import (
    BASE_URL,
    CLIENT_SIMULATION_DYNAMIC_HEADERS,
    CLIENT_SIMULATION_HEADERS,
    FALLBACK_BASE_URL,
    LOGIN_BASE_URL,
    WEB_CLIENT_HEADERS,
)
from .download_engine import  DownloadEngine
from .session_file import FileSessionMixin
from .model import (
    ApiCode,
    ApiReturnModel,
    CloudUserInfoModel,
    DeviceListResponse,
    DeviceModel,
    UserInfoModel,
)

logger = logging.getLogger(__name__)


class _ApiSession(requests.Session):
    # 主 API 域名的 netloc（预计算，避免每个请求重复 urlparse）
    _PRIMARY_NETLOC = urlparse(BASE_URL).netloc

    def __init__(self):
        super().__init__()
        self._use_fallback = False

    def request(self, method, url, **kwargs):
        parsed = urlparse(url)
        is_primary_api = parsed.netloc == self._PRIMARY_NETLOC and "/api/" in parsed.path
        if not is_primary_api:
            return super().request(method, url, **kwargs)

        fallback_url = url.replace(BASE_URL, FALLBACK_BASE_URL, 1)
        if self._use_fallback:
            return super().request(method, fallback_url, **kwargs)

        try:
            return super().request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as error:
            logger.warning("API 请求失败，切换备用地址: %s", error)
            response = super().request(method, fallback_url, **kwargs)
            self._use_fallback = True
            return response


class NetSession(FileSessionMixin, DownloadEngine):
    """123云盘 HTTP API 会话层，负责所有 HTTP 请求。

    对应 Flutter 项目 pan123next 中的 NetSession。
    文件/目录端点由 FileSessionMixin 提供，下载能力由 DownloadEngine 提供。
    """

    def __init__(self):
        self._user_info: Optional[UserInfoModel] = None
        self._http = _ApiSession()
        self._client_simulation_enabled = True
        self._error_backoff_retry_enabled = True
        self._http.headers.update(
            {
                "accept-encoding": "gzip",
                "content-type": "application/json",
                **CLIENT_SIMULATION_HEADERS,
            }
        )

        # 传输专用会话：用于下载（CDN）与上传（S3）。
        # 不携带 123pan 鉴权头，并扩大连接池以适配多线程分片传输，
        # 复用 TCP/TLS 连接，避免每个分片都重新握手。
        self._transfer = requests.Session()
        transfer_adapter = requests.adapters.HTTPAdapter(
            pool_connections=16, pool_maxsize=32
        )
        self._transfer.mount("https://", transfer_adapter)
        self._transfer.mount("https://", transfer_adapter)

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

    def set_client_simulation(self, enabled: bool):
        """在 Android 与 Web 客户端请求头之间切换。"""
        self._client_simulation_enabled = enabled
        mode_headers = CLIENT_SIMULATION_HEADERS if enabled else WEB_CLIENT_HEADERS
        for name in (
            *CLIENT_SIMULATION_HEADERS,
            *WEB_CLIENT_HEADERS,
            *CLIENT_SIMULATION_DYNAMIC_HEADERS,
        ):
            self._http.headers.pop(name, None)
        self._http.headers.update(mode_headers)
        self._update_headers()

    def set_error_backoff_retry(self, enabled: bool):
        """启用或关闭传输错误的退避重试。"""
        self._error_backoff_retry_enabled = enabled

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
                session.mount("https://", adapter)
        else:
            # 恢复无代理状态
            for session in (self._http, self._transfer):
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=16, pool_maxsize=32
                )
                session.mount("https://", adapter)
                session.mount("https://", adapter)
        self._http.proxies = proxies or {}
        self._transfer.proxies = proxies or {}

    def set_proxy_auth(
        self,
        proxy_type: str,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
    ):
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

    # 下载能力（多线程/单线程）由 DownloadEngine mixin 提供

    def _build_headers(self) -> dict[str, str]:
        """构建设备伪装请求头。"""
        device = self._user_info.device if self._user_info else None
        headers: dict[str, str] = {}
        if self._client_simulation_enabled and device:
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

    @staticmethod
    def _safe_json(
        resp: requests.Response,
    ) -> tuple[dict[str, Any], Optional[ApiReturnModel]]:
        """安全解析 JSON 响应，失败时返回错误模型。

        处理服务器返回空响应、HTML 错误页等非 JSON 内容的情况。
        """
        try:
            body = resp.json()
        except requests.exceptions.JSONDecodeError:
            return {}, ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=f"服务器返回无效 JSON (HTTP {resp.status_code})",
            )
        return body, None

    # ---- 账户 ----

    def login(self, user_name: str, password: str) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/b/api/user/sign_in")
        t0 = time.monotonic()
        try:
            resp = self._http.post(
                url,
                json={"type": 1, "passport": user_name, "password": password},
                timeout=(3, 5),
            )
        except requests.RequestException as e:
            logger.error("登录请求失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error("登录响应解析失败 (%.2fs): HTTP %s", elapsed, resp.status_code)
            return error
        code = body.get("code", -1)
        logger.info(
            "登录 %s (%.2fs): HTTP %s, code=%s",
            user_name,
            elapsed,
            resp.status_code,
            code,
        )
        if code != 200:
            msg = body.get("message", "")
            logger.error("登录失败: code=%s, msg=%s", code, msg)
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=msg,
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

    def get_user_info(self) -> ApiReturnModel:
        """获取当前登录用户的云盘信息（UID、空间、VIP等）。

        调用 /b/api/user/info 接口。
        """
        url = urljoin(BASE_URL, "/b/api/user/info")
        t0 = time.monotonic()
        try:
            resp = self._http.get(url, timeout=(3, 5))
        except requests.RequestException as e:
            logger.error("获取用户信息失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error("用户信息解析失败 (%.2fs): HTTP %s", elapsed, resp.status_code)
            return error
        code = body.get("code", -1)
        logger.info("获取用户信息 (%.2fs): code=%s", elapsed, code)
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=msg,
            )
        info = CloudUserInfoModel.from_dict(body)
        return ApiReturnModel(
            code=0,
            api_code=0,
            api_code_enum=ApiCode.success,
            msg="",
            data=info,
        )

    def get_device_list(self) -> ApiReturnModel:
        """获取当前账户的登录设备列表。

        调用 /b/api/user/device_list 接口。
        """
        url = urljoin(BASE_URL, "/b/api/user/device_list")
        params = {
            "operateType": 2,
            "event": "deviceManagement",
        }
        t0 = time.monotonic()
        try:
            resp = self._http.get(url, params=params, timeout=(3, 5))
        except requests.RequestException as e:
            logger.error("获取设备列表失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error("设备列表解析失败 (%.2fs): HTTP %s", elapsed, resp.status_code)
            return error
        code = body.get("code", -1)
        logger.info("获取设备列表 (%.2fs): code=%s, 设备数=%s",
                    elapsed, code, len(body.get("data", {}).get("DeviceS", [])))
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=msg,
            )
        device_data = DeviceListResponse.from_dict(body)
        return ApiReturnModel(
            code=0,
            api_code=0,
            api_code_enum=ApiCode.success,
            msg="",
            data=device_data,
        )

    # ---- 二维码登录 ----

    @staticmethod
    def _qr_headers(loginuuid: str) -> dict[str, str]:
        """二维码登录接口专用请求头（web 平台）。"""
        return {
            "loginuuid": loginuuid,
            "app-version": "3",
            "platform": "web",
            "content-type": "application/json;charset=UTF-8",
        }

    def qr_generate(self, loginuuid: str = "") -> ApiReturnModel:
        """获取二维码登录会话（uniID + url）。

        调用 login.123pan.com/api/user/qr-code/generate 接口。
        """
        url = urljoin(LOGIN_BASE_URL, "/api/user/qr-code/generate")
        t0 = time.monotonic()
        try:
            resp = self._http.get(
                url, headers=self._qr_headers(loginuuid), timeout=(3, 10)
            )
        except requests.RequestException as e:
            logger.error("获取二维码失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error("二维码响应解析失败 (%.2fs): HTTP %s", elapsed, resp.status_code)
            return error
        code = body.get("code", -1)
        logger.info("获取二维码 (%.2fs): code=%s", elapsed, code)
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=msg,
            )
        data = body.get("data", {})
        return ApiReturnModel(
            code=0,
            api_code=0,
            api_code_enum=ApiCode.success,
            msg="",
            data={
                "uniID": data.get("uniID", ""),
                "url": data.get("url", ""),
            },
        )

    def qr_poll(self, uni_id: str, loginuuid: str = "") -> ApiReturnModel:
        """轮询二维码扫码状态。

        调用 login.123pan.com/api/user/qr-code/result 接口。

        返回 data:
        - loginStatus: 0=等待扫码, 1=已扫码待确认, 2=拒绝, 3=确认登录, 4=过期
        - scanPlatform: 4=微信, 7=123云盘App（仅确认登录时从 login_type 取）
        - token: JWT token（仅 App 扫码确认时直接返回）
        """
        url = urljoin(LOGIN_BASE_URL, "/api/user/qr-code/result")
        params = {"uniID": uni_id}
        t0 = time.monotonic()
        try:
            resp = self._http.get(
                url,
                params=params,
                headers=self._qr_headers(loginuuid),
                timeout=(3, 10),
            )
        except requests.RequestException as e:
            logger.error("轮询扫码状态失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error("扫码状态解析失败 (%.2fs): HTTP %s", elapsed, resp.status_code)
            return error
        code = body.get("code", -1)
        data = body.get("data", {})
        logger.info("轮询扫码状态 (%.2fs): code=%s", elapsed, code)
        # code=200 表示用户已确认登录（映射为 loginStatus=3）
        if code == 200:
            return ApiReturnModel(
                code=0,
                api_code=0,
                api_code_enum=ApiCode.success,
                msg="",
                data={
                    "loginStatus": 3,
                    "scanPlatform": data.get("login_type", 0),
                    "token": data.get("token", ""),
                },
            )
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=msg,
            )
        return ApiReturnModel(
            code=0,
            api_code=0,
            api_code_enum=ApiCode.success,
            msg="",
            data={
                "loginStatus": data.get("loginStatus", -1),
                "scanPlatform": data.get("scanPlatform", 0),
            },
        )

    def qr_wx_code(self, uni_id: str, loginuuid: str = "") -> ApiReturnModel:
        """获取微信扫码登录凭证（wxCode）。

        调用 login.123pan.com/api/user/qr-code/wx_code 接口。
        """
        url = urljoin(LOGIN_BASE_URL, "/api/user/qr-code/wx_code")
        t0 = time.monotonic()
        try:
            resp = self._http.post(
                url,
                headers=self._qr_headers(loginuuid),
                json={"uniID": uni_id},
                timeout=(3, 10),
            )
        except requests.RequestException as e:
            logger.error("获取 wxCode 失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error("wxCode 响应解析失败 (%.2fs): HTTP %s", elapsed, resp.status_code)
            return error
        code = body.get("code", -1)
        logger.info("获取 wxCode (%.2fs): code=%s", elapsed, code)
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=msg,
            )
        data = body.get("data", {})
        return ApiReturnModel(
            code=0,
            api_code=0,
            api_code_enum=ApiCode.success,
            msg="",
            data={"wxCode": data.get("wxCode", "")},
        )

    def close(self):
        """关闭内部 requests.Session，释放连接池资源。"""
        for session in (self._http, self._transfer):
            try:
                session.close()
            except Exception:
                pass

    # 文件/目录端点由 FileSessionMixin 提供（见 session_file.py）
