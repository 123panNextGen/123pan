import json
import sqlite3
import threading
import time
from pathlib import Path

from .log import get_logger

logger = get_logger(__name__)

# 延迟导入 CONFIG_DIR 避免循环
_db_instance = None
_db_lock = threading.Lock()

UPLOAD_PART_SIZE = 5 * 1024 * 1024  # 5MB — 与 api.py UPLOAD_PART_SIZE 保持一致

CURRENT_SCHEMA_VERSION = 2


def _get_db_path():
    from .config import CONFIG_DIR
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR / "123pan.db"


def _safe_int(value, default=0, min_val=None, max_val=None):
    """安全地将配置值转换为 int，防止非法值崩溃。"""
    try:
        result = int(value)
    except (ValueError, TypeError):
        return default
    if min_val is not None and result < min_val:
        return min_val
    if max_val is not None and result > max_val:
        return max_val
    return result


class Database:
    """SQLite 单例数据库，WAL 模式，线程安全。"""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()
        self._migrate()
        self._init_defaults()

    @classmethod
    def instance(cls) -> "Database":
        global _db_instance
        if _db_instance is None:
            with _db_lock:
                if _db_instance is None:
                    _db_instance = cls(_get_db_path())
        return _db_instance

    @classmethod
    def reset(cls):
        global _db_instance
        with _db_lock:
            if _db_instance is not None:
                try:
                    _db_instance._conn.close()
                except Exception:
                    pass
                _db_instance = None

    def _create_tables(self):
        self._conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY NOT NULL,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS download_tasks (
                resume_id        TEXT PRIMARY KEY,
                account_name     TEXT NOT NULL DEFAULT '',
                file_name        TEXT NOT NULL,
                file_id          INTEGER NOT NULL,
                file_type        INTEGER NOT NULL DEFAULT 0,
                file_size        INTEGER NOT NULL DEFAULT 0,
                save_path        TEXT NOT NULL,
                current_dir_id   INTEGER NOT NULL DEFAULT 0,
                etag             TEXT NOT NULL DEFAULT '',
                s3key_flag       INTEGER NOT NULL DEFAULT 0,
                status           TEXT NOT NULL DEFAULT '等待中',
                progress         INTEGER NOT NULL DEFAULT 0,
                error            TEXT NOT NULL DEFAULT '',
                supports_resume  INTEGER NOT NULL DEFAULT 0,
                metadata_version INTEGER NOT NULL DEFAULT 2,
                created_at       REAL,
                updated_at       REAL
            );
            CREATE TABLE IF NOT EXISTS download_parts (
                resume_id     TEXT NOT NULL,
                part_index    INTEGER NOT NULL,
                start_byte    INTEGER NOT NULL,
                end_byte      INTEGER NOT NULL,
                expected_size INTEGER NOT NULL,
                actual_size   INTEGER NOT NULL DEFAULT 0,
                md5           TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (resume_id, part_index),
                FOREIGN KEY (resume_id) REFERENCES download_tasks(resume_id)
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS upload_tasks (
                task_id       TEXT PRIMARY KEY,
                account_name  TEXT NOT NULL DEFAULT '',
                file_name     TEXT NOT NULL,
                file_size     INTEGER NOT NULL DEFAULT 0,
                local_path    TEXT NOT NULL,
                target_dir_id INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT '等待中',
                progress      INTEGER NOT NULL DEFAULT 0,
                error         TEXT NOT NULL DEFAULT '',
                bucket        TEXT NOT NULL DEFAULT '',
                storage_node  TEXT NOT NULL DEFAULT '',
                upload_key    TEXT NOT NULL DEFAULT '',
                upload_id_s3  TEXT NOT NULL DEFAULT '',
                up_file_id    INTEGER NOT NULL DEFAULT 0,
                total_parts   INTEGER NOT NULL DEFAULT 0,
                block_size    INTEGER NOT NULL DEFAULT {UPLOAD_PART_SIZE},
                etag          TEXT NOT NULL DEFAULT '',
                created_at    REAL,
                updated_at    REAL
            );
            CREATE TABLE IF NOT EXISTS upload_parts (
                task_id    TEXT NOT NULL,
                part_index INTEGER NOT NULL,
                etag       TEXT NOT NULL DEFAULT '',
                uploaded   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (task_id, part_index),
                FOREIGN KEY (task_id) REFERENCES upload_tasks(task_id)
                    ON DELETE CASCADE
            );
        """)

    def _migrate(self):
        """基于 PRAGMA user_version 的 schema 迁移。"""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < CURRENT_SCHEMA_VERSION:
            if version < 2:
                # autoLogin --> rememberPassword + stayLoggedIn
                old_row = self._conn.execute(
                    "SELECT value FROM config WHERE key = 'autoLogin'"
                ).fetchone()
                if old_row:
                    was_auto = json.loads(old_row[0])
                    self._conn.execute(
                        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                        ("rememberPassword", json.dumps(bool(was_auto))),
                    )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                        ("stayLoggedIn", json.dumps(True)),
                    )
                    self._conn.execute("DELETE FROM config WHERE key = 'autoLogin'")
                self._conn.commit()
            self._conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    def _init_defaults(self):
        """首次创建时写入默认配置。"""
        defaults = {
            "defaultDownloadPath": str(Path.home() / "Downloads"),
            "askDownloadLocation": True,
            "rememberPassword": False,
            "stayLoggedIn": True,
            "maxDownloadThreads": 3,
            "maxUploadThreads": 16,
            "maxConcurrentDownloads": 3,
            "maxConcurrentUploads": 3,
            "retryMaxAttempts": 3,
            "retryBackoffFactor": 0.5,
        }
        with self._lock:
            for key, value in defaults.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            self._conn.commit()

    # ---- Config ----

    def get_config(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM config WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set_config(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
            self._conn.commit()

    def set_many_config(self, items: dict) -> None:
        with self._lock:
            for key, value in items.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            self._conn.commit()

    def get_all_config(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM config").fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}

    # ---- Download tasks ----

    def save_download_task(self, task: dict) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO download_tasks
                (resume_id, account_name, file_name, file_id, file_type,
                 file_size, save_path, current_dir_id, etag, s3key_flag,
                 status, progress, error, supports_resume, metadata_version,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(resume_id) DO UPDATE SET
                    account_name = excluded.account_name,
                    file_name = excluded.file_name,
                    file_id = excluded.file_id,
                    file_type = excluded.file_type,
                    file_size = excluded.file_size,
                    save_path = excluded.save_path,
                    current_dir_id = excluded.current_dir_id,
                    etag = excluded.etag,
                    s3key_flag = excluded.s3key_flag,
                    status = excluded.status,
                    progress = excluded.progress,
                    error = excluded.error,
                    supports_resume = excluded.supports_resume,
                    metadata_version = excluded.metadata_version,
                    updated_at = excluded.updated_at
                """,
                (
                    task["resume_id"], task.get("account_name", ""),
                    task["file_name"], task["file_id"],
                    task.get("file_type", 0), task.get("file_size", 0),
                    task["save_path"], task.get("current_dir_id", 0),
                    task.get("etag", ""), int(task.get("s3key_flag", 0)),
                    task.get("status", "等待中"), task.get("progress", 0),
                    task.get("error", ""),
                    int(task.get("supports_resume", 0)),
                    task.get("metadata_version", 2), now, now,
                ),
            )
            self._conn.commit()

    def get_download_task(self, resume_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM download_tasks WHERE resume_id = ?", (resume_id,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_download_tasks(self, account_name: str | None = None) -> list[dict]:
        with self._lock:
            if account_name:
                rows = self._conn.execute(
                    "SELECT * FROM download_tasks WHERE account_name = ?",
                    (account_name,),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM download_tasks").fetchall()
        return [dict(row) for row in rows]

    def update_download_task(self, resume_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [resume_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE download_tasks SET {set_clause} WHERE resume_id = ?",
                values,
            )
            self._conn.commit()

    def delete_download_task(self, resume_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM download_tasks WHERE resume_id = ?", (resume_id,)
            )
            self._conn.commit()

    # ---- Download parts ----

    def record_download_part(self, resume_id: str, part: dict) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO download_parts
                (resume_id, part_index, start_byte, end_byte,
                 expected_size, actual_size, md5)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    resume_id, part["index"], part["start"], part["end"],
                    part["expected_size"], part.get("actual_size", 0),
                    part.get("md5", ""),
                ),
            )
            self._conn.commit()

    def remove_download_part(self, resume_id: str, part_index: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM download_parts WHERE resume_id = ? AND part_index = ?",
                (resume_id, part_index),
            )
            self._conn.commit()

    def get_download_parts(self, resume_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM download_parts WHERE resume_id = ? ORDER BY part_index",
                (resume_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- Upload tasks ----

    def save_upload_task(self, task: dict) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO upload_tasks
                (task_id, account_name, file_name, file_size, local_path,
                 target_dir_id, status, progress, error, bucket,
                 storage_node, upload_key, upload_id_s3, up_file_id,
                 total_parts, block_size, etag, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    account_name = excluded.account_name,
                    file_name = excluded.file_name,
                    file_size = excluded.file_size,
                    local_path = excluded.local_path,
                    target_dir_id = excluded.target_dir_id,
                    status = excluded.status,
                    progress = excluded.progress,
                    error = excluded.error,
                    bucket = excluded.bucket,
                    storage_node = excluded.storage_node,
                    upload_key = excluded.upload_key,
                    upload_id_s3 = excluded.upload_id_s3,
                    up_file_id = excluded.up_file_id,
                    total_parts = excluded.total_parts,
                    block_size = excluded.block_size,
                    etag = excluded.etag,
                    updated_at = excluded.updated_at
                """,
                (
                    task["task_id"], task.get("account_name", ""),
                    task["file_name"], task.get("file_size", 0),
                    task["local_path"], task.get("target_dir_id", 0),
                    task.get("status", "等待中"), task.get("progress", 0),
                    task.get("error", ""), task.get("bucket", ""),
                    task.get("storage_node", ""), task.get("upload_key", ""),
                    task.get("upload_id_s3", ""), task.get("up_file_id", 0),
                    task.get("total_parts", 0),
                    task.get("block_size", UPLOAD_PART_SIZE),
                    task.get("etag", ""), now, now,
                ),
            )
            self._conn.commit()

    def get_upload_task(self, task_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM upload_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_upload_tasks(self, account_name: str | None = None) -> list[dict]:
        with self._lock:
            if account_name:
                rows = self._conn.execute(
                    "SELECT * FROM upload_tasks WHERE account_name = ?",
                    (account_name,),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM upload_tasks").fetchall()
        return [dict(row) for row in rows]

    def update_upload_task(self, task_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [task_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE upload_tasks SET {set_clause} WHERE task_id = ?",
                values,
            )
            self._conn.commit()

    def delete_upload_task(self, task_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM upload_tasks WHERE task_id = ?", (task_id,)
            )
            self._conn.commit()

    # ---- Upload parts ----

    def record_upload_part(self, task_id: str, part_index: int, etag: str = "") -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO upload_parts
                (task_id, part_index, etag, uploaded)
                VALUES (?, ?, ?, 1)""",
                (task_id, part_index, etag),
            )
            self._conn.commit()

    def get_upload_parts(self, task_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_id, part_index, etag, uploaded FROM upload_parts "
                "WHERE task_id = ? ORDER BY part_index",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]
