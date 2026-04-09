"""上传/下载共用的并发控制常量与慢启动调度工具。"""
import threading

# ---- 并发控制常量 ----
RATE_LIMIT_CODES = frozenset({429, 503})
MAX_RATE_LIMITS = 50
RATE_LIMIT_BACKOFF = 2
PROGRESS_INTERVAL = 0.1


def slow_start_scheduler(
    worker_fn, max_workers, part_queue, progress_lock,
    active_workers, allowed_workers, failed,
    probe_failed, probe_success_count, probe_phase, worker_feedback,
    is_stopped_fn, notify_conn_fn, thread_prefix="worker",
):
    """慢启动上探调度器：从 1 个 worker 开始逐个增加，遇到确认失败停止增长。"""
    threads = []
    workers_launched = 0

    if not part_queue.empty() and not failed[0] and not is_stopped_fn():
        t = threading.Thread(target=worker_fn, name=f"{thread_prefix}_0", daemon=True)
        threads.append(t)
        t.start()
        workers_launched = 1
        notify_conn_fn(1, allowed_workers[0])

    if workers_launched == 0:
        probe_phase[0] = False
        return

    while workers_launched < max_workers:
        worker_feedback.wait(timeout=60)
        worker_feedback.clear()
        if failed[0] or is_stopped_fn() or probe_failed[0]:
            break
        with progress_lock:
            alive = active_workers[0]
        if alive == 0:
            break
        with progress_lock:
            ok = probe_success_count[0]
        if ok >= workers_launched and not part_queue.empty():
            with progress_lock:
                allowed_workers[0] = workers_launched + 1
            notify_conn_fn(alive, allowed_workers[0])
            t = threading.Thread(
                target=worker_fn,
                name=f"{thread_prefix}_{workers_launched}",
                daemon=True,
            )
            threads.append(t)
            t.start()
            workers_launched += 1

    probe_phase[0] = False
    for t in threads:
        t.join()
