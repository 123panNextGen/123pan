"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import base64
import concurrent.futures
import logging
import re
import time
import threading
from pathlib import Path
from typing import Any, Optional, Callable
from urllib.parse import urljoin, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

from .model import (
    ApiCode,
    ApiReturnModel,
    CloudUserInfoModel,
    DeviceItemModel,
    DeviceListResponse,
    DeviceModel,
    FileItemModel,
    FileListResponse,
    UserInfoModel,
)

BASE_URL = "https://www.123pan.cn"
# 二维码登录专用域名（web 端登录接口）
LOGIN_BASE_URL = "https://login.123pan.com"

# 预编译正则：解析 HTML body 中 href='...' 形式的下载链接
# 避免每次调用 _resolve_download_url 时重复编译
_HREF_URL_RE = re.compile(r"href='(https?://[^']+)'")


class NetSession:
    """123云盘 HTTP API 会话层，负责所有 HTTP 请求。

    对应 Flutter 项目 pan123next 中的 NetSession。
    """

    def __init__(self):
        self._user_info: Optional[UserInfoModel] = None
        self._http = requests.Session()
        self._http.headers.update(
            {
                "accept-encoding": "gzip",
                "content-type": "application/json",
                "platform": "android",
                "devicename": "Xiaomi",
                "host": "www.123pan.cn",
                "app-version": "61",
                "x-app-version": "2.4.0",
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

    # ---- 多线程下载 ----

    def download_file_multithread(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        resume_offset: int = 0,
    ) -> bool:
        """多线程分片下载文件。

        先发送 HEAD 请求检查服务器是否支持 Range，
        若支持且文件大于分片阈值则使用多线程，否则回退到单线程。

        Args:
            url: 下载链接。
            file_path: 保存路径。
            file_size: 文件总大小（字节）。
            progress_callback: 进度回调 (downloaded, total)。
            resume_offset: 已下载字节数（断点续传），>0 时走单线程续传。

        Returns:
            是否下载成功。
        """
        logger.info(
            "下载文件: %s (%.2f MB), multi=%s, threads=%s, resume=%d",
            file_path.name,
            file_size / 1024 / 1024,
            self._multi_thread_enabled,
            self._num_threads,
            resume_offset,
        )

        if file_size == 0:
            logger.info("空文件，跳过下载: %s", file_path.name)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"")
            if progress_callback:
                progress_callback(0, 0)
            return True

        # 断点续传时走单线程续传（保证 Range + 追加模式的正确性）
        if resume_offset > 0:
            logger.debug("存在续传偏移，使用单线程续传")
            return self._download_single(
                url, file_path, file_size, progress_callback,
                resume_offset=resume_offset,
            )

        # 单线程路径：_download_single 已内联处理 JSON 重定向，无需预检。
        # 跳过不必要的 HTTP 请求，避免消耗一次性下载链接（如文件夹 zip）。
        if not self._multi_thread_enabled or self._num_threads <= 1:
            logger.debug("多线程已禁用，使用单线程")
            return self._download_single(url, file_path, file_size, progress_callback)

        if file_size < 5 * 1024 * 1024:
            logger.debug("文件小于 5MB，回退单线程")
            return self._download_single(url, file_path, file_size, progress_callback)

        # ---- 以下为多线程路径，需要预检 ----

        # 预检 JSON 重定向：CDN 可能返回 redirect_url 而非文件内容
        resolved = self._resolve_json_redirect_url(url)
        if resolved:
            url = resolved

        supports_range = self._check_range_support(url)
        if not supports_range:
            logger.debug("服务器不支持 Range，回退单线程")
            return self._download_single(url, file_path, file_size, progress_callback)

        logger.debug("启用多线程分片下载: %d 线程", self._num_threads)
        return self._download_chunked(url, file_path, file_size, progress_callback)

    def _check_range_support(self, url: str) -> bool:
        """检查 URL 是否支持 Range 请求。"""
        try:
            resp = self._transfer.head(url, timeout=5, allow_redirects=True)
            accept = resp.headers.get("Accept-Ranges", "")
            logger.debug(
                "Range 支持检查: Accept-Ranges=%s -> %s", accept, accept == "bytes"
            )
            return accept == "bytes"
        except requests.RequestException as e:
            logger.debug("Range 检查 HEAD 请求失败: %s", e)
            return False

    def _resolve_json_redirect_url(self, url: str) -> str:
        """快速探测 URL 是否为 JSON 重定向，若是则返回真实下载链接。

        发送一个小的 GET 请求（Range: bytes=0-0）检测 Content-Type，
        避免完整下载 JSON 响应体。仅用于多线程下载前的预检。
        """
        try:
            resp = self._transfer.get(
                url,
                headers={"Range": "bytes=0-0"},
                timeout=(3, 5),
                allow_redirects=True,
            )
            redirect_url = NetSession._check_json_redirect(resp)
            if redirect_url:
                logger.info("预检发现 JSON 重定向，切换到真实下载链接")
                return redirect_url
        except requests.RequestException as e:
            logger.debug("JSON 重定向预检请求失败: %s", e)
        return ""

    @staticmethod
    def _check_json_redirect(resp: requests.Response) -> str:
        """检查响应是否为 JSON 重定向，若是则返回 redirect_url。

        CDN 有时不返回文件内容，而是返回 JSON：
        {"code":0,"data":{"redirect_url":"https://..."}}

        Returns:
            重定向 URL，若非 JSON 重定向则返回空字符串。
        """
        content_type = resp.headers.get("Content-Type", "")
        if "json" not in content_type:
            return ""
        try:
            body = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return ""
        code = body.get("code", -1)
        if code != 0:
            return ""
        data = body.get("data") or {}
        redirect_url = data.get("RedirectUrl", data.get("redirect_url", ""))
        if redirect_url and redirect_url.startswith("http"):
            logger.debug("检测到 JSON 重定向: %s ...", redirect_url[:80])
            return redirect_url
        return ""

    def _download_single(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        _redirect_count: int = 0,
        resume_offset: int = 0,
    ) -> bool:
        """单线程流式下载（支持断点续传）。

        Args:
            _redirect_count: 内部参数，跟踪 JSON 重定向次数，防止无限循环。
            resume_offset: 已下载字节数，>0 时从该偏移续传（追加模式 + Range）。
        """
        if _redirect_count >= 3:
            logger.error("JSON 重定向次数过多，放弃下载: %s", file_path.name)
            return False

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        logger.debug("单线程下载开始: %s (resume_offset=%d)", file_path.name, resume_offset)

        # 连接级错误重试：文件夹 zip 等场景下 CDN 可能断连，重试最多 3 次
        max_conn_retries = 3
        for conn_attempt in range(max_conn_retries):
            t0 = time.monotonic()
            try:
                # 每次尝试根据现有临时文件大小计算续传偏移（断点续传）
                current_offset = temp_path.stat().st_size if temp_path.exists() else 0
                if current_offset >= file_size:
                    # 临时文件已完整，直接改名完成
                    if file_path.exists():
                        file_path.unlink()
                    temp_path.rename(file_path)
                    logger.info("临时文件已完整，直接完成: %s", file_path.name)
                    return True
                headers = {}
                mode = "wb"
                if current_offset > 0:
                    mode = "ab"
                    headers["Range"] = f"bytes={current_offset}-"
                    logger.info(
                        "断点续传: %s 从 %d/%d 字节继续",
                        file_path.name, current_offset, file_size,
                    )

                with self._transfer.get(
                    url, stream=True, timeout=(10, 60), headers=headers
                ) as resp:
                    resp.raise_for_status()

                    # 检测 JSON 重定向响应
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" in content_type:
                        body = resp.json()
                        data = body.get("data") or {}
                        redirect_url = data.get(
                            "RedirectUrl",
                            data.get("redirect_url", ""),
                        )
                        if redirect_url and redirect_url.startswith("http"):
                            logger.info(
                                "单线程下载遇到 JSON 重定向: %s -> %s ...",
                                file_path.name,
                                redirect_url[:80],
                            )
                            return self._download_single(
                                redirect_url, file_path, file_size,
                                progress_callback, _redirect_count + 1,
                                current_offset,
                            )
                        # JSON 响应但不是有效重定向，视为错误
                        msg = body.get("message", body.get("msg", "未知错误"))
                        logger.error("CDN 返回 JSON 错误: %s", body)
                        raise RuntimeError(
                            f"下载 {file_path.name} 失败，CDN 返回: {msg}"
                        )

                    downloaded = current_offset
                    last_report_ts = 0.0
                    with open(temp_path, mode) as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if self._download_limiter:
                                    wait = self._download_limiter.consume(len(chunk))
                                    if wait > 0:
                                        time.sleep(wait)
                                if progress_callback:
                                    now_ts = time.monotonic()
                                    if now_ts - last_report_ts >= 0.1:
                                        progress_callback(downloaded, file_size)
                                        last_report_ts = now_ts

                elapsed = time.monotonic() - t0
                logger.info(
                    "单线程下载完成: %s (%.2f MB / %.1fs)",
                    file_path.name,
                    downloaded / 1024 / 1024,
                    elapsed,
                )
                if temp_path.exists():
                    if file_path.exists():
                        file_path.unlink()
                    temp_path.rename(file_path)
                return True

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout,
            ) as e:
                elapsed = time.monotonic() - t0
                if conn_attempt < max_conn_retries - 1:
                    wait = (conn_attempt + 1) * 2.0
                    logger.warning(
                        "单线程下载连接中断 (第 %d/%d 次): %s (%.1fs)，%ss 后重试",
                        conn_attempt + 1,
                        max_conn_retries,
                        file_path.name,
                        elapsed,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    "单线程下载失败（连接中断 %d 次）: %s (%.1fs): %s:%s",
                    max_conn_retries,
                    file_path.name,
                    elapsed,
                    type(e).__name__,
                    e,
                )
                # 保留临时文件，供下次断点续传
                raise

            except Exception as e:
                elapsed = time.monotonic() - t0
                logger.error(
                    "单线程下载失败: %s (%.1fs): %s:%s",
                    file_path.name,
                    elapsed,
                    type(e).__name__,
                    e,
                )
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
        """多线程分片下载（每分片直接写入磁盘 .partN 文件，避免内存爆炸）。"""
        num_threads = self._num_threads
        chunk_size = max(self._chunk_size, file_size // num_threads)

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        progress_lock = threading.Lock()
        downloaded_bytes = [0]
        last_report = [0.0]
        errors: list = []
        errors_lock = threading.Lock()

        def _report_progress():
            if progress_callback:
                progress_callback(downloaded_bytes[0], file_size)

        def _download_chunk(start: int, end: int, index: int) -> bool:
            part_path = Path(str(temp_path) + f".part{index}")
            headers = {"Range": f"bytes={start}-{end}"}
            max_retries = 3
            for attempt in range(max_retries):
                chunk_downloaded = 0  # 本次尝试下载的字节数，失败时需回退
                try:
                    if part_path.exists():
                        part_path.unlink()
                    with self._transfer.get(
                        url,
                        headers=headers,
                        stream=True,
                        timeout=(10, 60),
                    ) as resp:
                        resp.raise_for_status()
                        with open(part_path, "wb") as pf:
                            for data in resp.iter_content(chunk_size=8192):
                                if data:
                                    pf.write(data)
                                    if self._download_limiter:
                                        wait = self._download_limiter.consume(len(data))
                                        if wait > 0:
                                            time.sleep(wait)
                                    chunk_downloaded += len(data)
                                    with progress_lock:
                                        downloaded_bytes[0] += len(data)
                                        now = time.monotonic()
                                        if now - last_report[0] >= 0.1:
                                            _report_progress()
                                            last_report[0] = now
                    return True
                except Exception as e:
                    if part_path.exists():
                        try:
                            part_path.unlink()
                        except OSError:
                            pass
                    # 回退本次尝试已计入的进度，避免重试时进度累加超100%
                    if chunk_downloaded > 0:
                        with progress_lock:
                            downloaded_bytes[0] -= chunk_downloaded
                    if attempt < max_retries - 1:
                        wait = (attempt + 1) * 1.0
                        logger.warning(
                            f"分片 {index} 第 {attempt + 1} 次失败，{wait:.0f}s 后重试: {e}"
                        )
                        time.sleep(wait)
                        continue
                    with errors_lock:
                        errors.append((index, e))
                    return False
            return False

        # 计算分片范围
        ranges: list[tuple[int, int]] = []
        start = 0
        while start < file_size:
            end = min(start + chunk_size - 1, file_size - 1)
            ranges.append((start, end))
            start = end + 1

        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=num_threads
            ) as executor:
                futures = {
                    executor.submit(_download_chunk, r[0], r[1], i): i
                    for i, r in enumerate(ranges)
                }

                for future in concurrent.futures.as_completed(futures):
                    if not future.result():
                        executor.shutdown(wait=False, cancel_futures=True)
                        for i in range(len(ranges)):
                            p = Path(str(temp_path) + f".part{i}")
                            if p.exists():
                                try:
                                    p.unlink()
                                except OSError:
                                    pass
                        err_msgs = [f"分片{idx}: {e}" for idx, e in errors]
                        raise RuntimeError(f"分片下载失败: {'; '.join(err_msgs)}")

            # 按顺序合并分片
            with open(temp_path, "wb") as out_f:
                for i in range(len(ranges)):
                    p = Path(str(temp_path) + f".part{i}")
                    try:
                        with open(p, "rb") as pf:
                            while True:
                                buf = pf.read(1024 * 1024)
                                if not buf:
                                    break
                                out_f.write(buf)
                        p.unlink()
                    except OSError as e:
                        raise RuntimeError(f"合并分片文件 {i} 失败: {e}")

            if temp_path.exists():
                if file_path.exists():
                    file_path.unlink()
                temp_path.rename(file_path)
            return True
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

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
        t0 = time.monotonic()
        try:
            resp = self._http.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            logger.error(
                "获取文件列表失败 (%.2fs): file_id=%s, page=%s, err=%s",
                time.monotonic() - t0,
                file_id,
                page,
                e,
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error(
                "文件列表响应异常: file_id=%s, HTTP %s", file_id, resp.status_code
            )
            return error
        code = body.get("code", -1)
        total = (
            body.get("data", {}).get("Total", 0)
            if isinstance(body.get("data"), dict)
            else 0
        )
        logger.debug(
            "获取文件列表 (%.2fs): file_id=%s, page=%s, code=%s, total=%s",
            elapsed,
            file_id,
            page,
            code,
            total,
        )
        if code == 2 and retry_login:
            logger.warning("token 过期，需重新登录: file_id=%s", file_id)
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", "token 过期"),
            )
        if code != 0:
            logger.error(
                "获取文件列表失败: file_id=%s, code=%s, msg=%s",
                file_id,
                code,
                body.get("message", ""),
            )
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        try:
            file_list_response = FileListResponse.from_dict(body)
        except Exception as e:
            logger.error("解析文件列表失败: %s", e)
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
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error(
                "创建文件夹失败: name=%s, parent=%s, err=%s",
                dir_name,
                parent_file_id,
                e,
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "创建文件夹 (%.2fs): name=%s, parent=%s, code=%s",
            elapsed,
            dir_name,
            parent_file_id,
            code,
        )
        if code != 0:
            logger.error(
                "创建文件夹失败: name=%s, code=%s, msg=%s",
                dir_name,
                code,
                body.get("message", ""),
            )
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

    def trash_file(
        self, file_info: dict | FileItemModel, operation: bool = True
    ) -> ApiReturnModel:
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
        op_name = "删除" if operation else "恢复"
        file_name = (
            payload.get("FileName", payload.get("fileName", "?"))
            if isinstance(payload, dict)
            else "?"
        )
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error("%s文件失败: name=%s, err=%s", op_name, file_name, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "%s文件 (%.2fs): name=%s, code=%s", op_name, elapsed, file_name, code
        )
        if code != 0:
            logger.error(
                "%s文件失败: name=%s, code=%s, msg=%s",
                op_name,
                file_name,
                code,
                body.get("message", ""),
            )
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

    def trash_delete(self, file_id_list: list[int]) -> ApiReturnModel:
        """从回收站永久删除指定文件。

        Args:
            file_id_list: 要永久删除的文件 ID 列表

        Returns:
            ApiReturnModel
        """
        url = "https://api.123278.com/b/api/file/delete"
        data = {
            "fileIdList": [{"fileId": fid} for fid in file_id_list],
            "event": "recycleDelete",
            "operatePlace": 1,
            "RequestSource": None,
        }
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error("永久删除请求失败: file_ids=%s, err=%s", file_id_list, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        msg = body.get("message", "")
        logger.debug(
            "永久删除 (%.2fs): file_ids=%s, code=%s, msg=%s",
            elapsed, file_id_list, code, msg,
        )
        if code != 0:
            logger.warning(
                "永久删除: file_ids=%s, code=%s, msg=%s",
                file_id_list, code, msg,
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg=msg,
        )

    # ---- 下载链接 ----

    def get_file_link(
        self, file_info: dict | FileItemModel
    ) -> ApiReturnModel:  # pylint: disable=protected-access
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
                    "s3keyFlag": file_info.get(
                        "S3KeyFlag", file_info.get("s3keyFlag", "")
                    ),
                    "type": file_info.get("Type", file_info.get("type", 0)),
                    "fileName": file_info.get(
                        "FileName", file_info.get("fileName", "")
                    ),
                    "size": file_info.get("Size", file_info.get("size", 0)),
                }
        file_name = request_data.get("fileName", "?")
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=request_data, timeout=10)
        except requests.RequestException as e:
            logger.error("获取下载链接失败: name=%s, err=%s", file_name, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "获取下载链接 (%.2fs): name=%s, type=%s, code=%s",
            elapsed,
            file_name,
            type_val,
            code,
        )
        if code != 0:
            # 5113/5114: 下载流量已超出限制
            if code in self._DOWNLOAD_LIMIT_CODES:
                logger.warning(
                    "下载流量已超出限制 (code=%s)，已绕过拦截: name=%s", code, file_name
                )
                # 不返回错误，继续执行 URL 重写绕过
            else:
                logger.error(
                    "获取下载链接失败: name=%s, code=%s, msg=%s",
                    file_name,
                    code,
                    body.get("message", ""),
                )
                return ApiReturnModel(
                    code=code,
                    api_code=code,
                    api_code_enum=ApiCode.fail,
                    msg=body.get("message", ""),
                )
        data = body.get("data") or {}

        # API 可能直接返回已解析的 CDN 下载链接（redirect_url）
        redirect_url = data.get("RedirectUrl", data.get("redirect_url", ""))
        if redirect_url:
            logger.info(
                "下载链接已获取（直链）: name=%s, size=%s",
                file_name,
                request_data.get("size", "?"),
            )
            return ApiReturnModel(
                code=0,
                api_code=200,
                api_code_enum=ApiCode.success,
                msg="",
                data=redirect_url,
            )

        # 否则使用 DownloadUrl 并通过 web-pro2 代理重写
        download_url = data.get("DownloadUrl", data.get("downloadUrl", ""))
        if not download_url:
            logger.error("响应中未找到下载链接: name=%s", file_name)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg="响应中未找到下载链接",
            )

        # 模拟 123pan_unlock.js: 重写下载 URL 绕过限制
        rewritten_url = self._rewrite_download_url(download_url)
        redirect_url = self._resolve_download_url(rewritten_url)
        logger.info(
            "下载链接已获取: name=%s, size=%s", file_name, request_data.get("size", "?")
        )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=redirect_url,
        )

    # ---- 下载流量限制错误码 ----
    _DOWNLOAD_LIMIT_CODES = frozenset({5113, 5114})

    @staticmethod
    def _b64_decode(data: str) -> str:
        """安全解码 base64，兼容标准 base64 和 URL-safe base64。"""
        if not data:
            return ""
        # 先尝试标准 base64，失败则尝试 URL-safe base64
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                return decoder(data).decode("utf-8")
            except Exception:
                continue
        return data

    @staticmethod
    def _b64_encode(data: str) -> str:
        """URL-safe base64 编码。"""
        return base64.urlsafe_b64encode(data.encode("utf-8")).decode()

    @staticmethod
    def _rewrite_download_url(url: str) -> str:
        """重写下载 URL，模拟 123pan_unlock.js 的绕过逻辑。

        将下载请求重定向到 web-pro2 代理，并添加 auto_redirect=0 参数，
        绕过官方 PC 端的下载流量限制。
        """
        try:
            parsed = urlparse(url)
            if "web-pro" in parsed.netloc:
                # 已经是 web-pro 域名，解码 params -> 添加 auto_redirect -> 重新编码
                qs = dict(
                    (k, v) for k, v in
                    (p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
                )
                params_b64 = qs.get("params", "")
                if params_b64:
                    decoded = NetSession._b64_decode(params_b64)
                    if not decoded:
                        decoded = params_b64
                    inner_parsed = urlparse(decoded)
                    inner_qs = dict(
                        (k, v) for k, v in
                        (p.split("=", 1) for p in inner_parsed.query.split("&") if "=" in p)
                    )
                    inner_qs["auto_redirect"] = "0"
                    new_query = "&".join(f"{k}={v}" for k, v in inner_qs.items())
                    new_inner = urlunparse(inner_parsed._replace(query=new_query))
                    qs["params"] = NetSession._b64_encode(new_inner)
                    new_query_str = "&".join(f"{k}={v}" for k, v in qs.items())
                    return urlunparse(parsed._replace(query=new_query_str))
                return url
            else:
                # 非 web-pro 域名，重写为 web-pro2 代理
                orig_parsed = urlparse(url)
                orig_qs = dict(
                    (k, v) for k, v in
                    (p.split("=", 1) for p in orig_parsed.query.split("&") if "=" in p)
                )
                orig_qs["auto_redirect"] = "0"
                new_query = "&".join(f"{k}={v}" for k, v in orig_qs.items())
                rewritten_orig = urlunparse(orig_parsed._replace(query=new_query))
                proxy_url = urlunparse((
                    "https",
                    "web-pro2.123952.com",
                    "/download-v2/",
                    "",
                    "params=" + NetSession._b64_encode(rewritten_orig)
                    + "&is_s3=0",
                    "",
                ))
                logger.debug("下载 URL 已重写到 web-pro2 代理")
                return proxy_url
        except Exception as e:
            logger.warning("下载 URL 重写失败，使用原始 URL: %s", e)
            return url

    def _resolve_download_url(self, url: str) -> str:
        """解析重定向获取真实下载链接。

        优先级：
        1. HTTP 3xx 重定向的 Location 头
        2. HTML body 中的 href='...' 链接
        3. download-v2 URL 中 base64 编码的 params 直接解码

        对应 Flutter 中用 dart:io HttpClient 手动跟随重定向的逻辑。
        """
        try:
            resp = self._transfer.get(url, timeout=10, allow_redirects=False)

            # 1. 优先检查 HTTP 重定向 Location 头
            location = resp.headers.get("Location", "")
            if location and resp.status_code in (301, 302, 303, 307, 308):
                logger.debug(
                    "下载 URL 已通过 Location 头解析 (status=%s): %s ...",
                    resp.status_code,
                    location[:80],
                )
                return location

            # 2. 检查 HTML body 中的 href 链接
            text = resp.text[:500]
            match = _HREF_URL_RE.search(text)
            if match:
                resolved = match.group(1)
                logger.debug("下载 URL 已通过 href 解析: %s ...", resolved[:80])
                return resolved

            logger.debug(
                "下载 URL 未找到重定向，返回原始 URL: status=%s, body=%.100s",
                resp.status_code,
                text,
            )
        except requests.RequestException as e:
            logger.warning("解析下载 URL HTTP 请求失败: %s", e)

        # 3. 兜底：如果是 download-v2 URL，直接解码 base64 params
        decoded = self._decode_download_v2_params(url)
        if decoded:
            logger.debug("下载 URL 已通过 base64 params 解码: %s ...", decoded[:80])
            return decoded

        return url

    @staticmethod
    def _decode_download_v2_params(url: str) -> str:
        """从 download-v2 URL 中解码 base64 编码的下载链接。

        格式: https://web-pro2.123952.com/download-v2/?params=<base64>&is_s3=0
        返回解码后的 URL，若非 download-v2 格式或解码失败则返回空字符串。
        """
        try:
            parsed = urlparse(url)
            if "/download-v2/" not in parsed.path:
                return ""
            qs = dict(
                (k, v) for k, v in
                (p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            )
            params_b64 = qs.get("params", "")
            if not params_b64:
                return ""
            decoded = NetSession._b64_decode(params_b64)
            if decoded.startswith("http"):
                return decoded
        except Exception:
            pass
        return ""

    # ---- 重命名 ----

    def rename_file(self, file_id: int, new_name: str) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/rename")
        data = {"driveId": 0, "fileId": file_id, "fileName": new_name}
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error(
                "重命名失败: file_id=%s, new_name=%s, err=%s", file_id, new_name, e
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "重命名 (%.2fs): file_id=%s, new_name=%s, code=%s",
            elapsed,
            file_id,
            new_name,
            code,
        )
        if code != 0:
            logger.error(
                "重命名失败: file_id=%s, code=%s, msg=%s",
                file_id,
                code,
                body.get("message", ""),
            )
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

    def mod_pid(self, file_id_list: list[int], target_parent_id: int) -> ApiReturnModel:
        """移动文件/文件夹到目标目录。

        调用 /b/api/file/mod_pid 接口。
        """
        url = urljoin(BASE_URL, "/b/api/file/mod_pid")
        data = {
            "fileIdList": [{"FileId": int(fid)} for fid in file_id_list],
            "parentFileId": int(target_parent_id),
        }
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error(
                "移动文件失败: target=%s, n=%d, err=%s",
                target_parent_id,
                len(file_id_list),
                e,
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "移动文件 (%.2fs): target=%s, n=%d, code=%s",
            elapsed,
            target_parent_id,
            len(file_id_list),
            code,
        )
        if code != 0:
            logger.error(
                "移动文件失败: target=%s, code=%s, msg=%s",
                target_parent_id,
                code,
                body.get("message", ""),
            )
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
