"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import sqlite3
import threading
from pathlib import Path

from .const import CONFIG_DIR
from .log import get_logger

logger = get_logger(__name__)

# 数据库文件路径（配置文件/文件缓存/传输任务统一存放）
DB_PATH = CONFIG_DIR / "123pan.db"


class Database:
    """轻量 SQLite 存储封装（单例）。

    提供统一的连接管理与线程安全访问，供配置、文件列表缓存、
    传输任务持久化等模块共用同一个数据库文件。
    """

    _instance = None
    _lock = threading.RLock()
    _path = DB_PATH

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    def set_path(cls, path):
        """设置数据库路径并重置连接（测试/迁移用）。"""
        with cls._lock:
            cls._path = Path(path)
            cls.reset()

    @classmethod
    def reset(cls):
        """关闭连接并重置单例（测试用）。"""
        with cls._lock:
            if cls._instance is not None and getattr(
                cls._instance, "_conn", None
            ) is not None:
                try:
                    cls._instance._conn.close()
                except Exception:
                    pass
            cls._instance = None

    @property
    def path(self) -> str:
        return str(self._path)

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._initialized = True
            path = self._path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error("创建数据库目录失败: %s", e)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False, timeout=10
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._create_tables()

    def _create_tables(self):
        """初始化数据表（幂等）。"""
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    user_name     TEXT PRIMARY KEY,
                    pass_word     TEXT NOT NULL DEFAULT '',
                    authorization TEXT NOT NULL DEFAULT '',
                    device_type   TEXT NOT NULL DEFAULT '',
                    os_version    TEXT NOT NULL DEFAULT '',
                    loginuuid     TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS dir_cache (
                    dir_id     TEXT PRIMARY KEY,
                    files      TEXT NOT NULL DEFAULT '[]',
                    total      INTEGER NOT NULL DEFAULT 0,
                    all_loaded INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS transfer_tasks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type      TEXT NOT NULL,
                    file_name      TEXT NOT NULL,
                    file_size      INTEGER NOT NULL DEFAULT 0,
                    local_path     TEXT NOT NULL DEFAULT '',
                    file_id        INTEGER NOT NULL DEFAULT 0,
                    target_dir_id  INTEGER NOT NULL DEFAULT 0,
                    current_dir_id INTEGER NOT NULL DEFAULT 0,
                    priority       INTEGER NOT NULL DEFAULT 1,
                    status         TEXT NOT NULL DEFAULT 'waiting',
                    progress       INTEGER NOT NULL DEFAULT 0,
                    resume_info    TEXT NOT NULL DEFAULT '{}',
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transfer_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type   TEXT NOT NULL,
                    file_name   TEXT NOT NULL,
                    file_size   INTEGER NOT NULL DEFAULT 0,
                    status      TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    finished_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def execute(self, sql, params=()):
        """执行写操作（自动提交）。"""
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur
            except sqlite3.Error as e:
                logger.error("SQL 执行失败: %s | %s", sql[:80], e)
                raise

    def query(self, sql, params=()):
        """查询多行，返回 dict 列表。"""
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
                return [dict(row) for row in rows]
            except sqlite3.Error as e:
                logger.error("SQL 查询失败: %s | %s", sql[:80], e)
                raise

    def query_one(self, sql, params=()):
        """查询单行，返回 dict 或 None。"""
        with self._lock:
            try:
                row = self._conn.execute(sql, params).fetchone()
                return dict(row) if row is not None else None
            except sqlite3.Error as e:
                logger.error("SQL 查询失败: %s | %s", sql[:80], e)
                raise

    def close(self):
        """关闭连接（应用退出时调用）。"""
        with self._lock:
            if self._initialized and getattr(self, "_conn", None) is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                self._initialized = False
