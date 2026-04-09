import queue
import threading

from src.app.common.concurrency import slow_start_scheduler


def test_slow_start_scheduler_returns_immediately_when_queue_is_empty():
    part_queue = queue.Queue()
    progress_lock = threading.Lock()
    active_workers = [0]
    allowed_workers = [1]
    failed = [False]
    probe_failed = [False]
    probe_success_count = [0]
    probe_phase = [True]

    class _Event:
        def wait(self, timeout=None):
            raise AssertionError("wait should not be called for an empty queue")

        def clear(self):
            raise AssertionError("clear should not be called for an empty queue")

    worker_feedback = _Event()

    slow_start_scheduler(
        worker_fn=lambda: None,
        max_workers=4,
        part_queue=part_queue,
        progress_lock=progress_lock,
        active_workers=active_workers,
        allowed_workers=allowed_workers,
        failed=failed,
        probe_failed=probe_failed,
        probe_success_count=probe_success_count,
        probe_phase=probe_phase,
        worker_feedback=worker_feedback,
        is_stopped_fn=lambda: False,
        notify_conn_fn=lambda active, allowed: None,
        thread_prefix="upload_worker",
    )

    assert probe_phase[0] is False
