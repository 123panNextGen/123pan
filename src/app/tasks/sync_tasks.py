"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from datetime import datetime, timezone

from PySide6.QtCore import QThread

from ..common.log import get_logger
from ..common.sync_store import SyncStore
from ..service.sync_service import (
    PHASE_DELETE,
    PHASE_SCAN_LOCAL,
    PHASE_SCAN_REMOTE,
    PHASE_UPLOAD,
    SyncService,
)
from ..common.i18n import tr

logger = get_logger(__name__)


class SyncRunThread(QThread):
    """同步运行线程：在后台执行一次完整同步（扫描 + 上传 + 删除）。

    通过 _SyncJobSignals 将进度/状态/结果发射回主线程。
    支持 cancel() 在分片边界中止（正在上传的文件完成当前文件后停止）。
    """

    def __init__(self, pan, job, signals):
        super().__init__()
        self._pan = pan
        self._job = job
        self.signals = signals
        self._cancel = False

    @property
    def is_cancelled(self):
        return self._cancel

    def cancel(self):
        """请求取消：置位后在当前文件处理完成后中止。"""
        self._cancel = True

    def run(self):
        job_id = int(self._job["id"])
        job_name = self._job.get("name", "")
        started_at = datetime.now(timezone.utc).isoformat()
        stats = {"added": 0, "updated": 0, "deleted": 0, "failed": 0, "skipped": 0}
        store = SyncStore()

        def _progress(rel_path, current, total, phase):
            if rel_path:
                self.signals.file_progress.emit(job_id, rel_path, current, total)
            else:
                phase_text = {
                    PHASE_SCAN_LOCAL: tr("sync.phase_scan_local", "扫描本地文件"),
                    PHASE_SCAN_REMOTE: tr("sync.phase_scan_remote", "获取云端列表"),
                    PHASE_UPLOAD: tr("sync.phase_upload", "上传"),
                    PHASE_DELETE: tr("sync.phase_delete", "删除"),
                }.get(phase, phase)
                self.signals.status.emit(job_id, phase_text)

        try:
            service = SyncService(self._pan._session)
            success, stats = service.run_sync(
                self._job, progress_callback=_progress, cancel=self
            )
            cancelled = self.is_cancelled

            if cancelled:
                status = "cancelled"
            elif success:
                status = "completed"
            else:
                status = "failed"

            summary = self._build_summary(stats, cancelled)
            self.signals.finished.emit(job_id, success and not cancelled, summary, stats)
            self._record_history(store, job_id, job_name, started_at, status, stats)
        except Exception as e:
            logger.error("同步运行异常: job=%s, err=%s", job_name, e)
            summary = tr("sync.error_run", "同步失败: {}").format(e)
            self.signals.finished.emit(job_id, False, summary, stats)
            self._record_history(
                store, job_id, job_name, started_at, "failed", stats, message=str(e)
            )

    @staticmethod
    def _build_summary(stats, cancelled):
        """构建运行结果摘要文本。"""
        parts = []
        if stats["added"]:
            parts.append(tr("sync.sum_added", "新增 {}").format(stats["added"]))
        if stats["updated"]:
            parts.append(tr("sync.sum_updated", "更新 {}").format(stats["updated"]))
        if stats["deleted"]:
            parts.append(tr("sync.sum_deleted", "删除 {}").format(stats["deleted"]))
        if stats["failed"]:
            parts.append(tr("sync.sum_failed", "失败 {}").format(stats["failed"]))
        if cancelled:
            return tr("sync.sum_cancelled", "已取消") + (
                "（" + "，".join(parts) + "）" if parts else ""
            )
        if not parts:
            return tr("sync.sum_uptodate", "已是最新，无需同步")
        return "，".join(parts)

    @staticmethod
    def _record_history(store, job_id, job_name, started_at, status, stats, message=""):
        """写入同步历史记录。"""
        try:
            store.add_history(
                job_id=job_id,
                job_name=job_name,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc).isoformat(),
                added=stats.get("added", 0),
                updated=stats.get("updated", 0),
                deleted=stats.get("deleted", 0),
                failed=stats.get("failed", 0),
                status=status,
                message=message,
            )
        except Exception as e:
            logger.error("记录同步历史失败: %s", e)
