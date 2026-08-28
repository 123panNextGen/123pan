"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from ..common.log import get_logger
from ..common.sync_store import SyncStore
from .signals import _SyncJobSignals
from .sync_tasks import SyncRunThread

logger = get_logger(__name__)

# 定时调度检查间隔（毫秒）。实际同步按各任务 interval_seconds 触发。
_SCHEDULER_TICK_MS = 15000


class SyncManager(QObject):
    """全局文件夹同步调度器。

    独立于同步界面存在（由 MainWindow 持有），保证应用最小化到系统托盘
    后同步任务仍按设定频率在后台运行。

    信号（主线程发射）：
        jobsChanged        -- 任务列表/状态变化
        jobStatusChanged   -- 某任务阶段状态文本
        jobFileProgress    -- 某任务文件级进度
        jobFileDone        -- 某任务单个文件处理完成
        jobFinished        -- 某任务运行结束
    """

    jobsChanged = Signal()
    jobStatusChanged = Signal(int, str)
    jobFileProgress = Signal(int, str, int, int)
    jobFileDone = Signal(int, str, bool, str)
    jobFinished = Signal(int, bool, str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = SyncStore()
        self._pan = None
        # job_id -> SyncRunThread（防止线程被 GC，且用于取消）
        self._running = {}

        self._timer = QTimer(self)
        self._timer.setInterval(_SCHEDULER_TICK_MS)
        self._timer.timeout.connect(self._check_scheduled)
        self._timer.start()

    # ---- pan 生命周期 ----

    def set_pan(self, pan):
        """设置登录后的 Pan123 实例；切换账号时取消所有运行中任务。"""
        if pan is self._pan:
            return
        self._cancel_all()
        self._pan = pan
        logger.info("SyncManager 已绑定 pan: %s",
                    getattr(pan, "user_name", "?") if pan is not None else None)

    def clear_pan(self):
        """退出登录时调用。"""
        self._cancel_all()
        self._pan = None

    # ---- 任务管理（写操作，均发射 jobsChanged） ----

    def get_jobs(self):
        return self._store.get_jobs()

    def get_history(self, limit=100):
        return self._store.get_history(limit=limit)

    def is_running(self, job_id):
        return job_id in self._running

    def running_ids(self):
        return set(self._running.keys())

    def add_job(self, **kwargs):
        job_id = self._store.add_job(**kwargs)
        self.jobsChanged.emit()
        return job_id

    def update_job(self, job_id, **kwargs):
        self._store.update_job(job_id, **kwargs)
        self.jobsChanged.emit()

    def set_job_enabled(self, job_id, enabled):
        self._store.set_job_enabled(job_id, enabled)
        if not enabled:
            self.cancel_job(job_id)
        self.jobsChanged.emit()

    def delete_job(self, job_id):
        self.cancel_job(job_id)
        self._store.delete_job(job_id)
        self.jobsChanged.emit()

    def clear_history(self):
        self._store.clear_history()

    # ---- 运行控制 ----

    def run_job(self, job_id):
        """立即运行指定任务（已在运行则忽略）。"""
        job = self._store.get_job(job_id)
        if job is None or self._pan is None:
            return
        if job_id in self._running:
            return
        self._start_thread(job)

    def run_all_enabled(self):
        """立即运行全部启用中的任务（托盘「立即同步」入口）。"""
        if self._pan is None:
            return
        for job in self._store.get_jobs(enabled_only=True):
            self.run_job(int(job["id"]))

    def cancel_job(self, job_id):
        thread = self._running.get(job_id)
        if thread is not None:
            thread.cancel()

    def shutdown(self):
        """应用退出：取消所有运行中任务并停止调度器。"""
        self._timer.stop()
        self._cancel_all()

    # ---- 内部实现 ----

    def _start_thread(self, job):
        job_id = int(job["id"])
        signals = _SyncJobSignals()
        thread = SyncRunThread(self._pan, job, signals)
        self._running[job_id] = thread

        signals.status.connect(self.jobStatusChanged.emit)
        signals.file_progress.connect(self.jobFileProgress.emit)
        signals.file_done.connect(self.jobFileDone.emit)
        signals.finished.connect(
            lambda jid, ok, summary, stats: self._on_job_finished(
                jid, ok, summary, stats, thread
            )
        )

        self._store.set_job_last_run(job_id)
        self.jobsChanged.emit()
        logger.info("同步任务启动: job=%s", job.get("name"))
        thread.start()

    def _on_job_finished(self, job_id, ok, summary, stats, thread):
        """任务结束：清理线程引用并通知界面。"""
        self._running.pop(job_id, None)
        if thread is not None and thread.isRunning():
            thread.wait(5000)
        self.jobFinished.emit(job_id, ok, summary, stats)
        self.jobsChanged.emit()
        logger.info("同步任务结束: job_id=%s, ok=%s", job_id, ok)

    def _cancel_all(self):
        for thread in list(self._running.values()):
            thread.cancel()
            if thread.isRunning():
                thread.wait(5000)
        self._running.clear()
        self.jobsChanged.emit()

    def _check_scheduled(self):
        """定时检查：按各任务 interval_seconds 触发后台同步。"""
        if self._pan is None:
            return
        now = datetime.now(timezone.utc)
        for job in self._store.get_jobs(enabled_only=True):
            job_id = int(job["id"])
            if job_id in self._running:
                continue
            interval = int(job.get("interval_seconds") or 0)
            if interval <= 0:
                continue  # 手动模式
            last = job.get("last_run_at") or ""
            if not last:
                self.run_job(job_id)
                continue
            try:
                last_dt = datetime.fromisoformat(last)
            except (ValueError, TypeError):
                self.run_job(job_id)
                continue
            if (now - last_dt).total_seconds() >= interval:
                self.run_job(job_id)
