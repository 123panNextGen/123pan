"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json
from datetime import datetime, timezone

from .database import Database
from .log import get_logger

logger = get_logger(__name__)

# 活动任务状态（内部存储用）
STATUS_WAITING = "waiting"
STATUS_RUNNING = "running"
STATUS_QUEUED = "queued"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# 历史记录可展示的状态
HISTORY_STATUSES = (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)


class TransferStore:
    """传输任务持久化存储（SQLite）。

    表：
        transfer_tasks    -- 活动任务（等待/排队/进行中/暂停），支撑断点续传
        transfer_history  -- 已完成/失败/取消的历史记录
    """

    def __init__(self):
        self._db = Database()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    # ---- 活动任务 ----

    def add_task(
        self,
        task_type,
        file_name,
        file_size,
        priority=1,
        status=STATUS_QUEUED,
        progress=0,
        local_path="",
        file_id=0,
        target_dir_id=0,
        current_dir_id=0,
        resume_info=None,
    ):
        """新增活动任务，返回自增 ID。"""
        now = self._now()
        cur = self._db.execute(
            """INSERT INTO transfer_tasks
               (task_type, file_name, file_size, local_path, file_id, target_dir_id,
                current_dir_id, priority, status, progress, resume_info,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_type,
                file_name,
                file_size,
                local_path,
                file_id,
                target_dir_id,
                current_dir_id,
                priority,
                status,
                progress,
                json.dumps(resume_info or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        return cur.lastrowid

    def update_task(
        self, task_id, status=None, progress=None, priority=None, resume_info=None
    ):
        """更新活动任务字段（仅更新非 None 字段）。"""
        fields = []
        params = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if progress is not None:
            fields.append("progress = ?")
            params.append(progress)
        if priority is not None:
            fields.append("priority = ?")
            params.append(priority)
        if resume_info is not None:
            fields.append("resume_info = ?")
            params.append(json.dumps(resume_info, ensure_ascii=False))
        if not fields:
            return
        params.append(self._now())
        params.append(task_id)
        self._db.execute(
            "UPDATE transfer_tasks SET " + ", ".join(fields) + ", updated_at = ?"
            " WHERE id = ?",
            tuple(params),
        )

    def remove_task(self, task_id):
        """删除活动任务。"""
        if task_id is None:
            return
        self._db.execute("DELETE FROM transfer_tasks WHERE id = ?", (task_id,))

    def get_active_tasks(self, task_type=None):
        """查询活动任务列表（按创建顺序）。"""
        sql = "SELECT * FROM transfer_tasks"
        params = ()
        if task_type:
            sql += " WHERE task_type = ?"
            params = (task_type,)
        sql += " ORDER BY id"
        return self._db.query(sql, params)

    def clear_active_tasks(self, task_type=None):
        """清空活动任务。"""
        if task_type:
            self._db.execute(
                "DELETE FROM transfer_tasks WHERE task_type = ?", (task_type,)
            )
        else:
            self._db.execute("DELETE FROM transfer_tasks")

    # ---- 历史记录 ----

    def add_history(
        self, task_type, file_name, file_size, status, created_at=None, finished_at=None
    ):
        """记录一条传输历史。"""
        now = self._now()
        self._db.execute(
            """INSERT INTO transfer_history
               (task_type, file_name, file_size, status, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                task_type,
                file_name,
                file_size,
                status,
                created_at or now,
                finished_at or now,
            ),
        )

    def get_history(self, limit=200):
        """查询历史记录（最新在前）。"""
        return self._db.query(
            "SELECT * FROM transfer_history ORDER BY id DESC LIMIT ?", (limit,)
        )

    def clear_history(self):
        """清空历史记录。"""
        self._db.execute("DELETE FROM transfer_history")
        logger.info("传输历史已清空")
