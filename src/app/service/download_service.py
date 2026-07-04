import concurrent.futures
import os
import threading
import time
from pathlib import Path

import requests

from ..common.config import ConfigManager
from ..common.log import get_logger

logger = get_logger(__name__)


class DownloadService:
    """下载服务。

    负责获取下载链接和执行下载（单线程/多线程）。
    """

    def __init__(self, session):
        self._session = session

    def link_by_fileDetail(self, file_detail, showlink=True):
        """按文件详情获取下载链接。

        Returns:
            str: 下载URL（成功）
            int: 错误码（失败）
        """
        result = self._session.get_file_link(file_detail)
        if result.code != 0:
            logger.error("获取下载链接失败，返回码: %s", result.code)
            logger.error(result.msg)
            return result.code
        redirect_url = result.data
        if showlink:
            logger.info("获取下载链接成功: %s", redirect_url)
        return redirect_url

    def download_from_url(self, url, file_name, download_path="download"):
        """从URL下载文件（简单单线程）。"""
        download_dir = Path(download_path)
        if not download_dir.exists():
            logger.info("创建下载目录")
            download_dir.mkdir(parents=True, exist_ok=True)

        file_path = download_dir / file_name
        temp_path = file_path.with_suffix(file_path.suffix + ".123pan")

        if temp_path.exists():
            temp_path.unlink()

        resp = self._session.transfer.get(url, stream=True, timeout=10)
        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        os.rename(temp_path, file_path)

    def stream_download_by_number(
        self, file_detail, redirect_url, download_dir, task=None, signals=None
    ):
        """完整下载流程，支持多线程分片、取消/暂停、进度回调。

        Args:
            file_detail: 文件详情 dict
            redirect_url: 下载URL
            download_dir: 保存目录
            task: 可选的任务控制对象（需有 _pause_event, is_cancelled）
            signals: 可选信号对象（需有 progress 信号）

        Returns:
            Path: 下载完成的文件路径
            str: "已取消" 如果被取消
        """
        fname = file_detail["FileName"]
        if file_detail.get("Type") == 1:
            fname += ".zip"

        out_path = Path(download_dir) / fname
        temp = out_path.with_suffix(out_path.suffix + ".123pan")

        Path(download_dir).mkdir(parents=True, exist_ok=True)

        if out_path.exists():
            raise FileExistsError(str(out_path))

        total = 0
        accept_ranges = False
        try:
            head = self._session.transfer.head(
                redirect_url, allow_redirects=True, timeout=30
            )
            head.raise_for_status()
            total = int(head.headers.get("Content-Length", 0) or 0)
            accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"
        except Exception:
            try:
                with self._session.transfer.get(
                    redirect_url, stream=True, timeout=30
                ) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0) or 0)
                    accept_ranges = (
                        r.headers.get("Accept-Ranges", "").lower() == "bytes"
                    )
            except Exception:
                total = 0
                accept_ranges = False

        try:
            if accept_ranges and total and total > 1024 * 1024 * 2:
                return self._multi_thread_download(
                    redirect_url, temp, out_path, total, task, signals
                )
            else:
                return self._single_thread_download(
                    redirect_url, temp, out_path, total, task, signals
                )
        except Exception:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
            raise

    def _single_thread_download(self, url, temp, out_path, total, task, signals):
        """单线程流式下载。"""
        with self._session.transfer.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            done = 0
            with open(temp, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if task:
                        try:
                            task._pause_event.wait()
                        except Exception:
                            pass
                        if task.is_cancelled:
                            f.close()
                            if temp.exists():
                                temp.unlink()
                            return "已取消"
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if total and signals:
                            signals.progress.emit(int(done * 100 / total))
        if task and task.is_cancelled:
            if temp.exists():
                temp.unlink()
            return "已取消"
        temp.replace(out_path)
        return out_path

    def _multi_thread_download(self, url, temp, out_path, total, task, signals):
        """多线程分片下载。"""
        max_download_threads = ConfigManager.get_setting("maxDownloadThreads", 8)
        max_download_threads = min(max(1, int(max_download_threads)), 16)

        num_threads = min(
            max_download_threads,
            max(1, int(total / (10 * 1024 * 1024))),
        )

        chunk_size = min(1024 * 1024, max(8192, total // (num_threads * 100)))
        part_size = total // num_threads

        downloaded = [0]
        dl_lock = threading.Lock()
        last_progress_time = [0]

        def download_range(start, end, index):
            part_path = Path(str(temp) + f".part{index}")
            headers = {"Range": f"bytes={start}-{end}"}
            try:
                with self._session.transfer.get(
                    url, headers=headers, stream=True, timeout=30
                ) as r:
                    r.raise_for_status()
                    with open(part_path, "wb") as pf:
                        for data in r.iter_content(chunk_size=chunk_size):
                            if task:
                                try:
                                    task._pause_event.wait()
                                except Exception:
                                    pass
                                if task.is_cancelled:
                                    return False
                            if data:
                                pf.write(data)
                                with dl_lock:
                                    downloaded[0] += len(data)
                                    current_time = time.time()
                                    if current_time - last_progress_time[0] > 0.1:
                                        if total and signals:
                                            signals.progress.emit(
                                                int(downloaded[0] * 100 / total)
                                            )
                                        last_progress_time[0] = current_time
                return True
            except requests.exceptions.RequestException as e:
                logger.error("下载分片 %s 失败: %s", index, e)
                if part_path.exists():
                    try:
                        part_path.unlink()
                    except OSError:
                        pass
                return False
            except Exception as e:
                logger.error("下载分片 %s 时发生未知错误: %s", index, e)
                if part_path.exists():
                    try:
                        part_path.unlink()
                    except OSError:
                        pass
                return False

        futures = []
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=num_threads, thread_name_prefix="download_range"
            ) as exe:
                for i in range(num_threads):
                    start = i * part_size
                    end = (
                        (start + part_size - 1)
                        if i < num_threads - 1
                        else (total - 1)
                    )
                    futures.append(exe.submit(download_range, start, end, i))

                ok = True
                for f in concurrent.futures.as_completed(futures):
                    if not f.result():
                        ok = False
                        break

            if not ok:
                raise RuntimeError("分片下载失败")
        except concurrent.futures.CancelledError:
            logger.warning("下载任务被取消")
            raise RuntimeError("下载任务被取消")

        if task and task.is_cancelled:
            for i in range(num_threads):
                p = Path(str(temp) + f".part{i}")
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            return "已取消"

        try:
            with open(temp, "wb") as out_f:
                for i in range(num_threads):
                    p = Path(str(temp) + f".part{i}")
                    try:
                        with open(p, "rb") as pf:
                            while True:
                                data = pf.read(1024 * 1024)
                                if not data:
                                    break
                                out_f.write(data)
                        p.unlink()
                    except OSError as e:
                        logger.error("合并分片文件 %s 时出错: %s", i, e)
                        if p.exists():
                            try:
                                p.unlink()
                            except OSError:
                                pass
                        raise RuntimeError(f"合并分片文件失败: {e}")
        except OSError as e:
            logger.error("创建临时文件时出错: %s", e)
            raise RuntimeError("合并分片文件失败")

        if task and task.is_cancelled:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
            return "已取消"

        temp.replace(out_path)
        return out_path
