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
    probe_thread_name, worker_feedback,
    is_stopped_fn, notify_conn_fn, thread_prefix="worker",
):
    """持续调度器：维持 allowed 个 normal worker + 1 个 probe worker。

    probe 收到首字节后转正（allowed += 1），立即启动下一个 probe。
    到达 max_workers 后停止 probe，仅维持 normal workers。
    """
    threads = []

    # 启动第 1 个 worker（即 probe）
    if part_queue.empty() or failed[0] or is_stopped_fn():
        return
    allowed_workers[0] = 1
    t = threading.Thread(target=worker_fn, name=f"{thread_prefix}_0", daemon=True)
    with progress_lock:
        probe_thread_name[0] = t.name
    threads.append(t)
    t.start()
    notify_conn_fn(1, 1)

    # 事件驱动监控循环
    while True:
        worker_feedback.wait(timeout=5)
        worker_feedback.clear()

        if failed[0] or is_stopped_fn():
            break

        with progress_lock:
            active = active_workers[0]
            allowed = allowed_workers[0]

        # 1. 补充 normal workers 到 allowed 水位
        while active < allowed and not part_queue.empty() and not failed[0]:
            t = threading.Thread(
                target=worker_fn,
                name=f"{thread_prefix}_{len(threads)}",
                daemon=True,
            )
            threads.append(t)
            t.start()
            active += 1

        # 2. 尝试启动 probe（无 probe + 未到上限 + 队列有活）
        with progress_lock:
            no_probe = probe_thread_name[0] is None
            can_probe = allowed_workers[0] < max_workers
        if no_probe and can_probe and not part_queue.empty() and not failed[0]:
            t = threading.Thread(
                target=worker_fn,
                name=f"{thread_prefix}_{len(threads)}",
                daemon=True,
            )
            threads.append(t)
            with progress_lock:
                probe_thread_name[0] = t.name
            t.start()

        # 3. 完成 / 安全网
        with progress_lock:
            if active_workers[0] == 0 and part_queue.empty():
                break
            if active_workers[0] == 0 and not part_queue.empty() and allowed_workers[0] >= 1:
                t = threading.Thread(
                    target=worker_fn,
                    name=f"{thread_prefix}_{len(threads)}",
                    daemon=True,
                )
                threads.append(t)
                t.start()

    for t in threads:
        t.join()
