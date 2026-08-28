"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone

from .const import CONFIG_DIR
from .database import Database
from .log import get_logger

logger = get_logger(__name__)

# 旧版 JSON 缓存路径（迁移检测用，迁移后改名备份）
FILE_DB_PATH = CONFIG_DIR / "file_list_db.json"

# 当前缓存格式版本（升级时递增，旧版本缓存自动失效重新拉取）
CURRENT_CACHE_VERSION = 2

# 缓存默认有效期（秒），超过此时间未更新的缓存视为过期。
# 该机制用于检测其他客户端操作导致的数据变更（如网页/手机端删除文件），
# 值不宜过大，否则界面会长期显示陈旧列表（用户需手动重建数据库才刷新）。
# 5 分钟以内其他客户端的增删改通常能自动反映到界面。
DEFAULT_CACHE_TTL_SECONDS = 5 * 60  # 5 分钟

# 内存缓存条目上限：防止浏览目录过多时内存无限增长
_CACHE_MAX_ENTRIES = 20


class FileListDB:
    """本地文件列表缓存（SQLite 存储）。

    每个账户使用独立的数据表（dir_cache_<account_hash>）：
        dir_id     TEXT PRIMARY KEY  -- 目录 ID
        files      TEXT              -- 文件信息 JSON 数组
        total      INTEGER           -- 文件总数
        all_loaded INTEGER           -- 是否已加载全部文件
        updated_at TEXT              -- 缓存更新时间 (ISO8601)

    使用方式：
        db = FileListDB()
        # 写入
        db.save_dir(0, files, total=100, all_loaded=True)
        # 读取
        files = db.get_dir(0)
        # 强制刷新
        db.mark_dirty(0)
        # 删除
        db.delete_db()
    """

    _instance = None
    _instances = {}
    _lock = threading.Lock()

    def __new__(cls, account_name=None):
        account_name = cls._resolve_account_name(account_name)
        with cls._lock:
            if cls._instance is None:
                cls._instances = {}
                cls._instance = True
            instance = cls._instances.get(account_name)
            if instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                instance._account_name = account_name
                cls._instances[account_name] = instance
            return instance

    def __init__(self, account_name=None):  # pylint: disable=unused-argument
        if self._initialized:
            return
        self._initialized = True
        account_hash = hashlib.sha256(self._account_name.encode("utf-8")).hexdigest()
        self.table_name = f"dir_cache_{account_hash}"
        self._dirty_dirs = set()
        # 内存缓存：dir_id(str) -> (files, total, all_loaded, updated_at)
        # 避免每次浏览目录都重复 json.loads 全量列表
        self._cache = {}
        self._db = Database()
        self._create_table()
        self._migrate_shared_cache()
        if self._account_name != "__default__":
            self._migrate_legacy_json()

    @staticmethod
    def _resolve_account_name(account_name):
        if account_name is None:
            from .config import ConfigManager

            account_name = ConfigManager.get_current_account_name()
        return str(account_name or "__default__")

    def _create_table(self):
        self._db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                dir_id     TEXT PRIMARY KEY,
                files      TEXT NOT NULL DEFAULT '[]',
                total      INTEGER NOT NULL DEFAULT 0,
                all_loaded INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

    def _migrate_shared_cache(self):
        """首次使用账户缓存时接管旧版共享表数据。"""
        if self._account_name == "__default__":
            return
        row = self._db.query_one("SELECT COUNT(*) AS count FROM dir_cache")
        if not row or row["count"] == 0:
            return
        target = self._db.query_one(
            f"SELECT COUNT(*) AS count FROM {self.table_name}"
        )
        if target and target["count"] == 0:
            self._db.execute(
                f"INSERT OR REPLACE INTO {self.table_name}"
                " (dir_id, files, total, all_loaded, updated_at)"
                " SELECT dir_id, files, total, all_loaded, updated_at FROM dir_cache"
            )
            self._db.execute("DELETE FROM dir_cache")
            logger.info("旧版共享文件列表缓存已迁移到账户独立表")

    # ---- 内存缓存 ----

    def _cache_put(self, dir_id, files, total, all_loaded, updated_at):
        """写入内存缓存，超限时淘汰最旧条目。"""
        with self._lock:
            self._cache[dir_id] = (files, total, all_loaded, updated_at)
            if len(self._cache) > _CACHE_MAX_ENTRIES:
                # dict 保持插入顺序，淘汰最早插入的键
                oldest = next(iter(self._cache))
                del self._cache[oldest]

    def _cache_get(self, dir_id):
        """读取内存缓存，命中返回 (files, total, all_loaded, updated_at)。"""
        with self._lock:
            cached = self._cache.get(dir_id)
            if cached is not None:
                # 命中后移到末尾，避免热点目录被 FIFO 淘汰。
                self._cache.pop(dir_id)
                self._cache[dir_id] = cached
            return cached

    def _cache_discard(self, dir_id):
        with self._lock:
            self._cache.pop(dir_id, None)

    def _migrate_legacy_json(self):
        """将旧版 JSON 缓存迁移到 SQLite（迁移后改名备份）。"""
        if not FILE_DB_PATH.exists():
            return
        try:
            with open(FILE_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            dirs = data.get("dirs", {})
            for dir_key, dir_data in dirs.items():
                self._db.execute(
                    f"INSERT OR REPLACE INTO {self.table_name}"
                    " (dir_id, files, total, all_loaded, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        str(dir_key),
                        json.dumps(dir_data.get("files", []), ensure_ascii=False),
                        int(dir_data.get("total", 0)),
                        1 if dir_data.get("all_loaded", False) else 0,
                        str(dir_data.get("updated_at", "")),
                    ),
                )
            backup = FILE_DB_PATH.with_suffix(".json.bak")
            FILE_DB_PATH.rename(backup)
            logger.info(
                "文件列表缓存已从 JSON 迁移到 SQLite: %d 个目录", len(dirs)
            )
        except Exception as e:
            logger.error("迁移文件列表缓存失败: %s", e)

    def get_dir(self, dir_id):
        """获取指定目录的文件列表。

        Args:
            dir_id: 目录 ID（整数或字符串）

        Returns:
            (files, total, all_loaded) 元组，未缓存时返回 (None, 0, False)
        """
        key = str(dir_id)
        cached = self._cache_get(key)
        if cached is not None:
            # 返回浅拷贝，避免调用方意外修改污染缓存
            return list(cached[0]), cached[1], cached[2]

        row = self._db.query_one(
            f"SELECT files, total, all_loaded, updated_at FROM {self.table_name}"
            " WHERE dir_id = ?",
            (key,),
        )
        if row is None:
            return None, 0, False
        try:
            files = json.loads(row["files"])
        except (ValueError, TypeError):
            files = []
        result = (files, int(row["total"]), bool(row["all_loaded"]))
        self._cache_put(
            key, result[0], result[1], result[2], row.get("updated_at", "")
        )
        return result

    def save_dir(self, dir_id, files, total=0, all_loaded=False):
        """保存目录的文件列表。

        Args:
            dir_id: 目录 ID
            files: 文件信息字典列表
            total: 文件总数
            all_loaded: 是否已加载全部文件
        """
        key = str(dir_id)
        updated_at = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            f"INSERT OR REPLACE INTO {self.table_name}"
            " (dir_id, files, total, all_loaded, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                key,
                json.dumps(files, ensure_ascii=False),
                int(total),
                1 if all_loaded else 0,
                updated_at,
            ),
        )
        with self._lock:
            self._dirty_dirs.discard(key)
        self._cache_put(key, files, int(total), bool(all_loaded), updated_at)

    def is_dirty(self, dir_id):
        """检查目录是否需要刷新（手动标记脏）。

        Args:
            dir_id: 目录 ID

        Returns:
            True 表示需要从服务器重新获取
        """
        with self._lock:
            return str(dir_id) in self._dirty_dirs

    def is_stale(self, dir_id, ttl_seconds=None):
        """检查目录缓存是否已过期（超过 TTL 未更新）。

        用于检测其他客户端操作导致的数据变更。
        缓存过期后会自动从服务器刷新，无需手动标记。

        Args:
            dir_id: 目录 ID
            ttl_seconds: 过期时间（秒），默认使用 DEFAULT_CACHE_TTL_SECONDS

        Returns:
            True 表示缓存已过期，需要从服务器刷新
        """
        if ttl_seconds is None:
            ttl_seconds = DEFAULT_CACHE_TTL_SECONDS

        # 注意：必须查询数据库（而非内存缓存），因为要检测外部进程对
        # 数据库的直接修改（如其他客户端操作导致的数据变更）。
        row = self._db.query_one(
            f"SELECT updated_at FROM {self.table_name} WHERE dir_id = ?",
            (str(dir_id),),
        )
        if row is None:
            return True  # 无缓存视为过期

        updated_at_str = row.get("updated_at", "")
        if not updated_at_str:
            return True

        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            age = datetime.now(timezone.utc) - updated_at
            return age > timedelta(seconds=ttl_seconds)
        except (ValueError, TypeError):
            return True

    def mark_dirty(self, dir_id):
        """标记目录需要强制刷新。"""
        key = str(dir_id)
        with self._lock:
            self._dirty_dirs.add(key)
            self._cache.pop(key, None)
            logger.debug("标记目录 %s 为脏", dir_id)

    def mark_all_dirty(self):
        """标记所有目录需要强制刷新。"""
        rows = self._db.query(f"SELECT dir_id FROM {self.table_name}")
        with self._lock:
            for row in rows:
                self._dirty_dirs.add(row["dir_id"])
                self._cache.pop(row["dir_id"], None)
            logger.debug("已标记所有 %d 个目录为脏", len(rows))

    def update_file_in_dir(self, dir_id, file_id, new_info=None, remove=False):
        """增量更新目录中的单个文件。

        Args:
            dir_id: 目录 ID
            file_id: 文件 ID
            new_info: 新的文件信息字典（添加或更新时提供）
            remove: 是否移除该文件
        """
        files, total, all_loaded = self.get_dir(dir_id)
        if files is None:
            return

        file_id_str = str(file_id)
        changed = False

        if remove:
            new_files = [
                f for f in files if str(f.get("FileId", "")) != file_id_str
            ]
            if len(new_files) != len(files):
                files = new_files
                total = max(0, total - 1)
                changed = True
        elif new_info:
            found = False
            for i, f in enumerate(files):
                if str(f.get("FileId", "")) == file_id_str:
                    files[i] = new_info
                    found = True
                    changed = True
                    break
            if not found:
                files.append(new_info)
                total += 1
                changed = True

        if changed:
            self.save_dir(dir_id, files, total=total, all_loaded=all_loaded)

    def delete_dir(self, dir_id):
        """从数据库中删除指定目录。"""
        key = str(dir_id)
        self._db.execute(
            f"DELETE FROM {self.table_name} WHERE dir_id = ?", (key,)
        )
        with self._lock:
            self._dirty_dirs.discard(key)
            self._cache.pop(key, None)

    def delete_db(self):
        """清空文件列表缓存（保留其他表数据）。"""
        self._db.execute(f"DELETE FROM {self.table_name}")
        with self._lock:
            self._dirty_dirs.clear()
            self._cache.clear()
        logger.info("文件列表缓存已清空")

    def get_stats(self):
        """获取数据库统计信息。

        Returns:
            (目录数, 总文件数) 元组
        """
        rows = self._db.query(f"SELECT files FROM {self.table_name}")
        file_count = 0
        for row in rows:
            try:
                file_count += len(json.loads(row["files"]))
            except (ValueError, TypeError):
                pass
        return len(rows), file_count
