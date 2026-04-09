import errno
import hashlib
import math
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

import requests

from .config import CONFIG_DIR
from .concurrency import (
    RATE_LIMIT_CODES, MAX_RATE_LIMITS, RATE_LIMIT_BACKOFF,
    MAX_PART_RETRIES, PROGRESS_INTERVAL, slow_start_scheduler,
)
from .database import Database, get_download_part_size
from .log import get_logger

logger = get_logger(__name__)

PART_SIZE = 5 * 1024 * 1024  # 默认值，运行时由 get_download_part_size() 覆盖
MIN_PARALLEL_SIZE = 2 * 1024 * 1024
IO_CHUNK_SIZE = 1024 * 1024
MAX_PART_QUEUE_ATTEMPTS = 3
DEFAULT_MAX_DOWNLOAD_THREADS = 1


def build_resume_id(account_name, file_id, save_path):
    raw = f"{account_name}|{file_id}|{Path(save_path)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _compute_md5(file_path):
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def get_temp_dir(resume_id):
    """返回下载临时目录: CONFIG_DIR/tmp/<resume_id>/"""
    return CONFIG_DIR / "tmp" / resume_id


def get_part_path(resume_id, index):
    return get_temp_dir(resume_id) / f"part{index}"


def get_merged_path(resume_id):
    return get_temp_dir(resume_id) / "merged"


def cleanup_temp_dir(resume_id):
    temp_dir = get_temp_dir(resume_id)
    if temp_dir.exists():
        shutil.rmtree(str(temp_dir), ignore_errors=True)


def _replace_output_file(src_path: Path, out_path: Path) -> Path:
    try:
        src_path.replace(out_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(src_path), str(out_path))
    return out_path


# ---- signal helpers ----

def _notify_progress(signals, total, downloaded):
    if signals and total:
        signals.progress.emit(int(downloaded * 100 / total))


def _notify_conn_info(signals, active_workers, max_workers):
    if signals and hasattr(signals, "conn_info"):
        signals.conn_info.emit(active_workers, max_workers)


def _notify_status(signals, status):
    if signals and hasattr(signals, "status"):
        signals.status.emit(status)


# ---- task state helpers ----

def _is_task_cancelled(task):
    return bool(task and getattr(task, "is_cancelled", False))


def _is_task_paused(task):
    return bool(task and getattr(task, "pause_requested", False))


def _get_stop_result(task):
    if _is_task_cancelled(task):
        return "cancelled"
    if _is_task_paused(task):
        return "paused"
    return None


# ---- DB helpers ----

def _save_download_status(resume_id, total, downloaded, status, error=None):
    if not resume_id:
        return
    progress = int(downloaded * 100 / total) if total else 0
    Database.instance().update_download_task(
        resume_id,
        progress=progress,
        status=status,
        error=error or "",
        file_size=total,
    )


def _reset_partial_download(
    part_path, downloaded, progress_lock, byte_count,
    signals, total, resume_id, index,
):
    if byte_count:
        with progress_lock:
            downloaded[0] = max(0, downloaded[0] - byte_count)
            current = downloaded[0]
        _notify_progress(signals, total, current)
    Database.instance().remove_download_part(resume_id, index)
    if part_path.exists():
        try:
            part_path.unlink()
        except OSError:
            logger.warning("删除失败的分片文件失败: %s", part_path)


def _cleanup_parts(resume_id, part_indexes):
    for index in part_indexes:
        p = get_part_path(resume_id, index)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                logger.warning("删除分片失败: %s", p)


# ---- part plan ----

def _build_parts(total, part_size=None):
    if total <= 0:
        return []
    ps = part_size or get_download_part_size()
    part_count = math.ceil(total / ps)
    parts = []
    for index in range(part_count):
        start = index * ps
        end = min(start + ps - 1, total - 1)
        parts.append({
            "index": index, "start": start, "end": end,
            "expected_size": end - start + 1,
        })
    return parts


def _validate_existing_parts(resume_id, part_plan):
    db = Database.instance()
    stored = {p["part_index"]: p for p in db.get_download_parts(resume_id)}
    reusable_indexes = []
    downloaded = 0
    for part in part_plan:
        index = int(part["index"])
        sp = stored.get(index)
        if not sp:
            continue
        p_path = get_part_path(resume_id, index)
        expected_size = int(part["expected_size"])
        expected_hash = sp.get("md5")
        if not expected_hash or not p_path.exists():
            db.remove_download_part(resume_id, index)
            continue
        actual_size = p_path.stat().st_size
        if actual_size != expected_size:
            try:
                p_path.unlink()
            except OSError:
                pass
            db.remove_download_part(resume_id, index)
            continue
        actual_hash = _compute_md5(p_path)
        if actual_hash != expected_hash:
            try:
                p_path.unlink()
            except OSError:
                pass
            db.remove_download_part(resume_id, index)
            continue
        reusable_indexes.append(index)
        downloaded += expected_size
    return downloaded, reusable_indexes


def _prepare_resume_metadata(out_path, total, resume_task, multi_part_enabled):
    if not resume_task:
        return None
    db = Database.instance()
    task_data = {
        "resume_id": resume_task.resume_id,
        "account_name": resume_task.account_name,
        "file_name": resume_task.file_name,
        "file_id": resume_task.file_id,
        "file_type": resume_task.file_type,
        "file_size": total or resume_task.file_size,
        "save_path": str(out_path),
        "current_dir_id": getattr(resume_task, "current_dir_id", 0),
        "etag": resume_task.etag,
        "s3key_flag": int(resume_task.s3key_flag),
        "status": resume_task.status,
        "progress": resume_task.progress,
        "error": resume_task.last_error,
        "supports_resume": int(multi_part_enabled),
        "metadata_version": getattr(resume_task, "metadata_version", 2),
    }
    db.save_download_task(task_data)
    return task_data


# ---- probe ----

def _probe_download(redirect_url):
    total = 0
    accept_ranges = False
    try:
        head = requests.head(redirect_url, allow_redirects=True, timeout=30)
        head.raise_for_status()
        total = int(head.headers.get("Content-Length", 0) or 0)
        accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"
    except requests.RequestException:
        try:
            with requests.get(redirect_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0) or 0)
                accept_ranges = r.headers.get("Accept-Ranges", "").lower() == "bytes"
        except requests.RequestException:
            return 0, False
    return total, accept_ranges


# ---- download part ----

def _download_part(
    redirect_url, part, resume_id, downloaded, progress_lock,
    last_progress_time, signals, total, task, speed_tracker,
):
    index = int(part["index"])
    start = int(part["start"])
    end = int(part["end"])
    part_path = get_part_path(resume_id, index)
    part_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Range": f"bytes={start}-{end}"}
    retry_count = 0
    queue_attempt = int(part.get("attempt", 0))
    io_chunk_size = min(IO_CHUNK_SIZE, max(8192, int(part["expected_size"] / 100) or 8192))

    while retry_count < MAX_PART_RETRIES:
        attempt_downloaded = 0
        stop_result = _get_stop_result(task)
        if stop_result:
            return stop_result
        try:
            md5 = hashlib.md5()
            with requests.get(redirect_url, headers=headers, stream=True, timeout=60) as resp:
                if resp.status_code in RATE_LIMIT_CODES:
                    return "rate_limited"
                resp.raise_for_status()
                with open(part_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=io_chunk_size):
                        stop_result = _get_stop_result(task)
                        if stop_result:
                            _reset_partial_download(
                                part_path, downloaded, progress_lock,
                                attempt_downloaded, signals, total, resume_id, index,
                            )
                            return stop_result
                        if not chunk:
                            continue
                        f.write(chunk)
                        md5.update(chunk)
                        attempt_downloaded += len(chunk)
                        with progress_lock:
                            downloaded[0] += len(chunk)
                            now = time.time()
                            if speed_tracker:
                                speed_tracker.record(downloaded[0])
                            if now - last_progress_time[0] > PROGRESS_INTERVAL:
                                _notify_progress(signals, total, downloaded[0])
                                last_progress_time[0] = now
            actual_size = part_path.stat().st_size
            if actual_size != int(part["expected_size"]):
                raise RuntimeError(f"分片 {index} 大小不匹配")
            Database.instance().record_download_part(resume_id, {
                "index": index, "start": start, "end": end,
                "expected_size": int(part["expected_size"]),
                "actual_size": actual_size, "md5": md5.hexdigest(),
            })
            part["attempt"] = 0
            return "ok"
        except (requests.RequestException, RuntimeError, OSError) as exc:
            _reset_partial_download(
                part_path, downloaded, progress_lock,
                attempt_downloaded, signals, total, resume_id, index,
            )
            retry_count += 1
            if retry_count >= MAX_PART_RETRIES:
                queue_attempt += 1
                part["attempt"] = queue_attempt
                if queue_attempt >= MAX_PART_QUEUE_ATTEMPTS:
                    return "fatal"
                return "retryable"
            time.sleep(2 ** retry_count)
    return "fatal"


# ---- multi-part download ----

def _download_with_resume(redirect_url, out_path, total, signals, task, resume_task, speed_tracker):
    resume_id = resume_task.resume_id
    part_plan = _build_parts(total)
    _prepare_resume_metadata(out_path, total, resume_task, True)

    reused_bytes, reusable_indexes = _validate_existing_parts(resume_id, part_plan)
    reusable = set(reusable_indexes)
    _save_download_status(resume_id, total, reused_bytes, "校验中")
    _notify_status(signals, "校验中")
    _notify_progress(signals, total, reused_bytes)

    part_queue = queue.Queue()
    for part in part_plan:
        if int(part["index"]) not in reusable:
            part_queue.put(part)

    max_workers = min(
        max(1, int(Database.instance().get_config("maxDownloadThreads", DEFAULT_MAX_DOWNLOAD_THREADS))),
        16,
    )
    active_workers = [0]
    allowed_workers = [1]
    failed = [False]
    rate_limit_count = [0]
    downloaded = [reused_bytes]
    progress_lock = threading.Lock()
    last_progress_time = [0.0]
    probe_phase = [True]
    probe_failed = [False]
    probe_success_count = [0]
    worker_feedback = threading.Event()

    if speed_tracker and reused_bytes:
        speed_tracker.record(reused_bytes)

    def worker():
        with progress_lock:
            active_workers[0] += 1
            _notify_conn_info(signals, active_workers[0], allowed_workers[0])
        try:
            while not failed[0]:
                stop_result = _get_stop_result(task)
                if stop_result:
                    return
                with progress_lock:
                    if active_workers[0] > allowed_workers[0]:
                        return
                try:
                    part = part_queue.get_nowait()
                except queue.Empty:
                    return

                result = _download_part(
                    redirect_url, part, resume_id, downloaded, progress_lock,
                    last_progress_time, signals, total, task, speed_tracker,
                )
                if result == "ok":
                    _save_download_status(resume_id, total, downloaded[0], "下载中")
                    with progress_lock:
                        probe_success_count[0] += 1
                    worker_feedback.set()
                    continue
                if result in ("cancelled", "paused"):
                    return
                if result == "rate_limited":
                    with progress_lock:
                        rate_limit_count[0] += 1
                        if rate_limit_count[0] > MAX_RATE_LIMITS:
                            failed[0] = True
                            return
                        new_limit = max(1, active_workers[0] - 1)
                        if new_limit < allowed_workers[0]:
                            allowed_workers[0] = new_limit
                        if probe_phase[0]:
                            probe_failed[0] = True
                            probe_phase[0] = False
                        _notify_conn_info(signals, active_workers[0], allowed_workers[0])
                    part_queue.put(part)
                    worker_feedback.set()
                    time.sleep(RATE_LIMIT_BACKOFF)
                    continue
                if result == "retryable":
                    part_queue.put(part)
                    if probe_phase[0]:
                        with progress_lock:
                            probe_failed[0] = True
                            probe_phase[0] = False
                        worker_feedback.set()
                    continue
                with progress_lock:
                    if probe_phase[0]:
                        probe_failed[0] = True
                        probe_phase[0] = False
                worker_feedback.set()
                failed[0] = True
                return
        finally:
            with progress_lock:
                active_workers[0] -= 1
                _notify_conn_info(signals, active_workers[0], allowed_workers[0])
            worker_feedback.set()

    _save_download_status(resume_id, total, reused_bytes, "下载中")
    _notify_status(signals, "下载中")

    slow_start_scheduler(
        worker_fn=worker,
        max_workers=max_workers,
        part_queue=part_queue,
        progress_lock=progress_lock,
        active_workers=active_workers,
        allowed_workers=allowed_workers,
        failed=failed,
        probe_failed=probe_failed,
        probe_success_count=probe_success_count,
        probe_phase=probe_phase,
        worker_feedback=worker_feedback,
        is_stopped_fn=lambda: bool(_get_stop_result(task)),
        notify_conn_fn=lambda a, al: _notify_conn_info(signals, a, al),
        thread_prefix="dl_worker",
    )

    _notify_conn_info(signals, 0, allowed_workers[0])
    _notify_progress(signals, total, downloaded[0])

    if _is_task_paused(task):
        _save_download_status(resume_id, total, downloaded[0], "已暂停", "")
        _notify_status(signals, "已暂停")
        return "已暂停"

    if _is_task_cancelled(task):
        _save_download_status(resume_id, total, downloaded[0], "已取消", "用户取消下载")
        _notify_status(signals, "已取消")
        if getattr(task, "cleanup_on_cancel", False):
            Database.instance().delete_download_task(resume_id)
            cleanup_temp_dir(resume_id)
        return "已取消"

    if failed[0]:
        _save_download_status(resume_id, total, downloaded[0], "失败", "分片下载失败")
        _notify_status(signals, "失败")
        raise RuntimeError("分片下载失败")

    # ---- 合并阶段 ----
    _save_download_status(resume_id, total, downloaded[0], "合并中")
    _notify_status(signals, "合并中")
    merged_path = get_merged_path(resume_id)
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    # 清理旧的合并文件（防止上次合并中断残留）
    if merged_path.exists():
        try:
            merged_path.unlink()
        except OSError:
            pass
    try:
        with open(merged_path, "wb") as output:
            for part in part_plan:
                pp = get_part_path(resume_id, int(part["index"]))
                with open(pp, "rb") as pf:
                    while True:
                        chunk = pf.read(IO_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
    except OSError as exc:
        raise RuntimeError(f"合并分片文件失败: {exc}") from exc

    if _is_task_paused(task):
        _save_download_status(resume_id, total, downloaded[0], "已暂停", "")
        _notify_status(signals, "已暂停")
        try:
            merged_path.unlink()
        except OSError:
            pass
        return "已暂停"

    if _is_task_cancelled(task):
        _save_download_status(resume_id, total, downloaded[0], "已取消", "用户取消下载")
        if getattr(task, "cleanup_on_cancel", False):
            Database.instance().delete_download_task(resume_id)
            cleanup_temp_dir(resume_id)
        return "已取消"

    # etag 校验（去引号；分片格式如 md5-3 跳过校验）
    expected_etag = (resume_task.etag or "").strip().strip('"').lower()
    if expected_etag and "-" not in expected_etag:
        actual_etag = _compute_md5(merged_path).lower()
        if actual_etag != expected_etag:
            cleanup_temp_dir(resume_id)
            Database.instance().delete_download_task(resume_id)
            raise RuntimeError("整文件校验失败，需要重新下载")

    # 移动到目标位置
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _replace_output_file(merged_path, out_path)
    cleanup_temp_dir(resume_id)
    return out_path


# ---- single stream download ----

def _download_single_stream(redirect_url, out_path, total, signals, task, speed_tracker):
    temp_dir = CONFIG_DIR / "tmp" / "single_stream"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}_{out_path.name}"
    _notify_status(signals, "下载中")
    with requests.get(redirect_url, stream=True, timeout=30) as response:
        response.raise_for_status()
        done = 0
        last_t = 0.0
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                stop_result = _get_stop_result(task)
                if stop_result:
                    f.close()
                    if temp_path.exists():
                        temp_path.unlink()
                    status = "已暂停" if stop_result == "paused" else "已取消"
                    _notify_status(signals, status)
                    return status
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if speed_tracker:
                    speed_tracker.record(done)
                now = time.time()
                if now - last_t > PROGRESS_INTERVAL:
                    _notify_progress(signals, total, done)
                    last_t = now
    _notify_progress(signals, total, done)
    if _is_task_paused(task):
        if temp_path.exists():
            temp_path.unlink()
        _notify_status(signals, "已暂停")
        return "已暂停"
    if _is_task_cancelled(task):
        if temp_path.exists():
            temp_path.unlink()
        _notify_status(signals, "已取消")
        return "已取消"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _replace_output_file(temp_path, out_path)
    return out_path


# ---- entry point ----

def stream_download_from_url(
    redirect_url, out_path, signals=None, task=None,
    overwrite=False, resume_task=None, speed_tracker=None,
):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    total, accept_ranges = _probe_download(redirect_url)
    multi_part_enabled = bool(accept_ranges and total and total > MIN_PARALLEL_SIZE)

    if resume_task:
        _prepare_resume_metadata(out_path, total, resume_task, multi_part_enabled)

    try:
        if multi_part_enabled:
            return _download_with_resume(
                redirect_url, out_path, total, signals, task,
                resume_task, speed_tracker,
            )
        return _download_single_stream(
            redirect_url, out_path, total, signals, task, speed_tracker,
        )
    except Exception as exc:
        _notify_status(signals, "失败")
        if resume_task:
            try:
                db = Database.instance()
                existing = db.get_download_task(resume_task.resume_id)
                progress = existing.get("progress", 0) if existing else 0
                db.update_download_task(
                    resume_task.resume_id,
                    status="失败", progress=progress,
                    error=str(exc), file_size=total or resume_task.file_size,
                )
            except Exception:
                logger.warning("写入下载失败状态时异常: %s", resume_task.resume_id)
        raise
