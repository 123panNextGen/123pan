"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from datetime import datetime, timezone

from .database import Database
from .log import get_logger

logger = get_logger(__name__)

# 同步方向
DIRECTION_UPLOAD = "upload"  # 仅本地上传到云端

# 同步间隔（秒）：0 = 手动
INTERVAL_MANUAL = 0
INTERVAL_30S = 30
INTERVAL_1M = 60
INTERVAL_5M = 300
INTERVAL_30M = 1800
INTERVAL_1H = 3600


class SyncStore:
    """同步任务持久化存储（SQLite）。

    表：
        sync_jobs    -- 同步任务配置
        sync_history -- 每次同步运行结果
    """

    def __init__(self):
        self._db = Database()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    # ---- 同步任务 ----

    def add_job(
        self,
        name,
        local_path,
        remote_dir_id,
        remote_dir_name="",
        direction=DIRECTION_UPLOAD,
        interval_seconds=INTERVAL_MANUAL,
        enabled=True,
        delete_remote=False,
    ):
        """新增同步任务，返回自增 ID。"""
        now = self._now()
        cur = self._db.execute(
            """INSERT INTO sync_jobs
               (name, local_path, remote_dir_id, remote_dir_name, direction,
                interval_seconds, enabled, delete_remote, last_run_at,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)""",
            (
                name,
                local_path,
                int(remote_dir_id),
                remote_dir_name,
                direction,
                int(interval_seconds),
                1 if enabled else 0,
                1 if delete_remote else 0,
                now,
                now,
            ),
        )
        return cur.lastrowid

    def update_job(
        self, job_id, name=None, local_path=None, remote_dir_id=None,
        remote_dir_name=None, interval_seconds=None, delete_remote=None,
    ):
        """更新同步任务配置（仅更新非 None 字段）。"""
        fields = []
        params = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if local_path is not None:
            fields.append("local_path = ?")
            params.append(local_path)
        if remote_dir_id is not None:
            fields.append("remote_dir_id = ?")
            params.append(int(remote_dir_id))
        if remote_dir_name is not None:
            fields.append("remote_dir_name = ?")
            params.append(remote_dir_name)
        if interval_seconds is not None:
            fields.append("interval_seconds = ?")
            params.append(int(interval_seconds))
        if delete_remote is not None:
            fields.append("delete_remote = ?")
            params.append(1 if delete_remote else 0)
        if not fields:
            return
        params.append(self._now())
        params.append(int(job_id))
        self._db.execute(
            "UPDATE sync_jobs SET " + ", ".join(fields) + ", updated_at = ?"
            " WHERE id = ?",
            tuple(params),
        )

    def set_job_enabled(self, job_id, enabled):
        """启用/禁用同步任务。"""
        self._db.execute(
            "UPDATE sync_jobs SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, self._now(), int(job_id)),
        )

    def set_job_last_run(self, job_id):
        """记录任务最近运行时间。"""
        self._db.execute(
            "UPDATE sync_jobs SET last_run_at = ?, updated_at = ? WHERE id = ?",
            (self._now(), self._now(), int(job_id)),
        )

    def delete_job(self, job_id):
        """删除同步任务（含其历史记录与指纹）。"""
        self._db.execute("DELETE FROM sync_jobs WHERE id = ?", (int(job_id),))
        self._db.execute("DELETE FROM sync_history WHERE job_id = ?", (int(job_id),))
        self._db.execute(
            "DELETE FROM sync_fingerprints WHERE job_id = ?", (int(job_id),)
        )

    def get_jobs(self, enabled_only=False):
        """查询全部同步任务（按创建顺序）。"""
        sql = "SELECT * FROM sync_jobs"
        params = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id"
        return self._db.query(sql, params)

    def get_job(self, job_id):
        """查询单个同步任务。"""
        return self._db.query_one(
            "SELECT * FROM sync_jobs WHERE id = ?", (int(job_id),)
        )

    # ---- 运行历史 ----

    def add_history(
        self, job_id, job_name, started_at, finished_at="",
        added=0, updated=0, deleted=0, failed=0, status="completed",
        message="",
    ):
        """记录一次同步运行结果。"""
        self._db.execute(
            """INSERT INTO sync_history
               (job_id, job_name, started_at, finished_at,
                added, updated, deleted, failed, status, message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(job_id),
                job_name,
                started_at,
                finished_at,
                int(added),
                int(updated),
                int(deleted),
                int(failed),
                status,
                message,
            ),
        )

    def get_history(self, limit=100):
        """查询同步历史（最新在前）。"""
        return self._db.query(
            "SELECT * FROM sync_history ORDER BY id DESC LIMIT ?", (int(limit),)
        )

    def get_job_history(self, job_id, limit=50):
        """查询单个任务的同步历史。"""
        return self._db.query(
            "SELECT * FROM sync_history WHERE job_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (int(job_id), int(limit)),
        )

    def clear_history(self):
        """清空同步历史。"""
        self._db.execute("DELETE FROM sync_history")
        logger.info("同步历史已清空")

    # ---- 文件指纹 ----

    def set_fingerprint(self, job_id, rel_path, size, mtime):
        """记录文件同步后的 (size, mtime) 指纹。

        用于检测同尺寸文件的修改（本地 size/mtime 变化即视为变更），
        避免每次同步重复上传未变化的文件。
        """
        self._db.execute(
            """INSERT OR REPLACE INTO sync_fingerprints
               (job_id, rel_path, size, mtime) VALUES (?, ?, ?, ?)""",
            (int(job_id), rel_path, int(size), int(mtime)),
        )

    def get_fingerprints(self, job_id):
        """获取任务的全部指纹：{rel_path: (size, mtime)}。"""
        rows = self._db.query(
            "SELECT rel_path, size, mtime FROM sync_fingerprints"
            " WHERE job_id = ?",
            (int(job_id),),
        )
        return {row["rel_path"]: (int(row["size"]), int(row["mtime"])) for row in rows}

    def remove_fingerprint(self, job_id, rel_path):
        """删除单个文件指纹（云端删除时清理）。"""
        self._db.execute(
            "DELETE FROM sync_fingerprints WHERE job_id = ? AND rel_path = ?",
            (int(job_id), rel_path),
        )

    def clear_fingerprints(self, job_id):
        """清空任务指纹（任务删除时）。"""
        self._db.execute(
            "DELETE FROM sync_fingerprints WHERE job_id = ?", (int(job_id),)
        )
