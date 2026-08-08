"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import concurrent.futures
import logging
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# CDN 限流 / 服务器临时故障状态码：需要更长的退避重试，而非直接判失败
_THROTTLE_STATUS_CODES = (429, 500, 502, 503, 504)


def _is_throttle_error(exc):
    """判断异常是否属于限流（429）或服务器临时故障（5xx）。"""
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return exc.response.status_code in _THROTTLE_STATUS_CODES
    return False


def _throttle_backoff(exc, attempt):
    """计算限流/临时故障的重试退避秒数。

    优先采用响应头 Retry-After；否则指数退避（2s, 4s, 8s...封顶 30s），
    并加少量随机抖动，避免多分片同时重试再次触发限流。
    """
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 1.0), 60.0)
            except ValueError:
                pass
    return min(2 ** attempt * 2.0, 30.0) + random.uniform(0, 0.5)


class DownloadCancelledError(Exception):
    """下载被用户取消。

    与普通异常的区别：取消时不删除临时文件（保留断点续传数据），
    由 download_file_multithread 捕获后返回 False 表示未完成。
    """


class DownloadEngine:
    """多线程/单线程文件下载能力（mixin）。

    注意：本类不定义 __init__，依赖子类（NetSession）初始化传输会话
    与下载配置。
    """

    def download_file_multithread(
        self,
        url: str,
        file_path: Path,
        file_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        resume_offset: int = 0,
        cancel_event: Optional[threading.Event] = None,
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
            cancel_event: 取消事件，置位时中止下载并返回 False（保留临时文件）。

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

        try:
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
                    cancel_event=cancel_event,
                )

            # 单线程路径：_download_single 已内联处理 JSON 重定向，无需预检。
            # 跳过不必要的 HTTP 请求，避免消耗一次性下载链接（如文件夹 zip）。
            if not self._multi_thread_enabled or self._num_threads <= 1:
                logger.debug("多线程已禁用，使用单线程")
                return self._download_single(
                    url, file_path, file_size, progress_callback,
                    cancel_event=cancel_event,
                )

            if file_size < 5 * 1024 * 1024:
                logger.debug("文件小于 5MB，回退单线程")
                return self._download_single(
                    url, file_path, file_size, progress_callback,
                    cancel_event=cancel_event,
                )

            # ---- 以下为多线程路径，需要预检 ----

            # 预检 JSON 重定向：CDN 可能返回 redirect_url 而非文件内容
            resolved = self._resolve_json_redirect_url(url)
            if resolved:
                url = resolved

            supports_range = self._check_range_support(url)
            if not supports_range:
                logger.debug("服务器不支持 Range，回退单线程")
                return self._download_single(
                    url, file_path, file_size, progress_callback,
                    cancel_event=cancel_event,
                )

            logger.debug("启用多线程分片下载: %d 线程", self._num_threads)
            return self._download_chunked(
                url, file_path, file_size, progress_callback,
                cancel_event=cancel_event,
            )
        except DownloadCancelledError:
            logger.info("下载已取消: %s", file_path.name)
            return False

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
            redirect_url = self._check_json_redirect(resp)
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
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """单线程流式下载（支持断点续传）。

        Args:
            _redirect_count: 内部参数，跟踪 JSON 重定向次数，防止无限循环。
            resume_offset: 已下载字节数，>0 时从该偏移续传（追加模式 + Range）。
            cancel_event: 取消事件，置位时抛出 DownloadCancelledError
                （保留临时文件供续传，由上层捕获返回 False）。
        """
        if _redirect_count >= 3:
            logger.error("JSON 重定向次数过多，放弃下载: %s", file_path.name)
            return False

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        logger.debug(
            "单线程下载开始: %s (resume_offset=%d)", file_path.name, resume_offset
        )

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
                                current_offset, cancel_event,
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
                            if cancel_event and cancel_event.is_set():
                                raise DownloadCancelledError()
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

            except DownloadCancelledError:
                # 取消：保留临时文件，供下次断点续传
                logger.info(
                    "下载取消: %s (已下载 %d 字节)", file_path.name, current_offset
                )
                raise

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
        cancel_event: Optional[threading.Event] = None,
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
            # 普通错误最多重试 3 次；限流/临时故障退避更久，最多重试 6 次
            max_retries = 3
            max_throttle_retries = 6
            for attempt in range(max_throttle_retries):
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
                                if cancel_event and cancel_event.is_set():
                                    raise DownloadCancelledError()
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
                except DownloadCancelledError:
                    raise
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
                    is_throttle = _is_throttle_error(e)
                    limit = max_throttle_retries if is_throttle else max_retries
                    if attempt < limit - 1:
                        if is_throttle:
                            wait = _throttle_backoff(e, attempt)
                        else:
                            wait = (attempt + 1) * 1.0
                        logger.warning(
                            "分片 %d 第 %d 次失败（%s），%.0fs 后重试: %s",
                            index,
                            attempt + 1,
                            "限流" if is_throttle else "错误",
                            wait,
                            e,
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
                    try:
                        result = future.result()
                    except DownloadCancelledError:
                        # 仅取消未启动的任务；分片清理推迟到外层 handler 完成：
                        # 此时 executor 已全部退出，文件句柄全部关闭，
                        # 避免 Windows 上对打开中的文件 unlink 失败留下残留
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise
                    if not result:
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
        except DownloadCancelledError:
            # 取消：等待 executor 全部退出后清理分片临时文件，再上抛
            for i in range(len(ranges)):
                p = Path(str(temp_path) + f".part{i}")
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            raise
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise
