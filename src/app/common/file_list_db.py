"""
本地文件列表数据库（JSON 格式）。

设计原则：
- 以目录 ID 为键，存储该目录下的完整文件列表
- 增量更新：仅标记需要刷新的目录，避免每次全量请求
- 支持强制刷新指定目录和清空整个数据库
- 线程安全：使用简单的锁保护写操作
"""

import json
import os
import threading
import tempfile
from pathlib import Path

from .config import CONFIG_DIR
from .log import get_logger

logger = get_logger(__name__)

FILE_DB_PATH = CONFIG_DIR / "file_list_db.json"


class FileListDB:
    """本地文件列表数据库。

    数据结构：
    {
        "version": 1,
        "dirs": {
            "<dir_id>": {
                "files": [ { ...file_info... }, ... ],
                "total": 100,
                "all_loaded": true,
                "updated_at": "2024-01-01T00:00:00"
            }
        }
    }

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
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data = None
        self._dirty_dirs = set()
        self._load()

    def _load(self):
        """从磁盘加载数据库。"""
        if not FILE_DB_PATH.exists():
            self._data = {"version": 1, "dirs": {}}
            logger.debug("文件列表数据库不存在，创建空数据库")
            return

        try:
            with open(FILE_DB_PATH, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            if "version" not in self._data:
                self._data["version"] = 1
            if "dirs" not in self._data:
                self._data["dirs"] = {}
            logger.debug(
                "文件列表数据库已加载: %d 个目录",
                len(self._data.get("dirs", {})),
            )
        except Exception as e:
            logger.error("加载文件列表数据库失败: %s", e)
            self._data = {"version": 1, "dirs": {}}

    def _save(self):
        """原子写入数据库到磁盘。"""
        try:
            if not FILE_DB_PATH.parent.exists():
                FILE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(FILE_DB_PATH.parent),
                prefix=".file_list_db_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, str(FILE_DB_PATH))
                logger.debug("文件列表数据库已保存")
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.error("保存文件列表数据库失败: %s", e)

    def get_dir(self, dir_id):
        """获取指定目录的文件列表。

        Args:
            dir_id: 目录 ID（整数或字符串）

        Returns:
            (files, total, all_loaded) 元组，未缓存时返回 (None, 0, False)
        """
        dir_key = str(dir_id)
        with self._lock:
            dir_data = self._data.get("dirs", {}).get(dir_key)
            if dir_data is None:
                return None, 0, False
            return (
                dir_data.get("files", []),
                dir_data.get("total", 0),
                dir_data.get("all_loaded", False),
            )

    def save_dir(self, dir_id, files, total=0, all_loaded=False):
        """保存目录的文件列表。

        Args:
            dir_id: 目录 ID
            files: 文件信息字典列表
            total: 文件总数
            all_loaded: 是否已加载全部文件
        """
        from datetime import datetime

        dir_key = str(dir_id)
        with self._lock:
            if "dirs" not in self._data:
                self._data["dirs"] = {}
            self._data["dirs"][dir_key] = {
                "files": files,
                "total": total,
                "all_loaded": all_loaded,
                "updated_at": datetime.now().isoformat(),
            }
            self._dirty_dirs.discard(dir_key)
            self._save()

    def is_dirty(self, dir_id):
        """检查目录是否需要刷新。

        Args:
            dir_id: 目录 ID

        Returns:
            True 表示需要从服务器重新获取
        """
        dir_key = str(dir_id)
        with self._lock:
            return dir_key in self._dirty_dirs

    def mark_dirty(self, dir_id):
        """标记目录需要强制刷新。"""
        dir_key = str(dir_id)
        with self._lock:
            self._dirty_dirs.add(dir_key)
            logger.debug("标记目录 %s 为脏", dir_key)

    def mark_all_dirty(self):
        """标记所有目录需要强制刷新。"""
        with self._lock:
            keys = list(self._data.get("dirs", {}).keys())
            for key in keys:
                self._dirty_dirs.add(key)
            logger.debug("已标记所有 %d 个目录为脏", len(keys))

    def update_file_in_dir(self, dir_id, file_id, new_info=None, remove=False):
        """增量更新目录中的单个文件。

        Args:
            dir_id: 目录 ID
            file_id: 文件 ID
            new_info: 新的文件信息字典（添加或更新时提供）
            remove: 是否移除该文件
        """
        dir_key = str(dir_id)
        with self._lock:
            dir_data = self._data.get("dirs", {}).get(dir_key)
            if dir_data is None:
                return

            files = dir_data.get("files", [])
            file_id_str = str(file_id)

            if remove:
                dir_data["files"] = [
                    f for f in files if str(f.get("FileId", "")) != file_id_str
                ]
                dir_data["total"] = max(0, dir_data.get("total", 0) - 1)
            elif new_info:
                found = False
                for i, f in enumerate(files):
                    if str(f.get("FileId", "")) == file_id_str:
                        files[i] = new_info
                        found = True
                        break
                if not found:
                    files.append(new_info)
                    dir_data["total"] = dir_data.get("total", 0) + 1
                dir_data["files"] = files

            from datetime import datetime
            dir_data["updated_at"] = datetime.now().isoformat()
            self._save()

    def delete_dir(self, dir_id):
        """从数据库中删除指定目录。"""
        dir_key = str(dir_id)
        with self._lock:
            if "dirs" in self._data:
                self._data["dirs"].pop(dir_key, None)
                self._dirty_dirs.discard(dir_key)
                self._save()

    def delete_db(self):
        """删除整个数据库文件。"""
        with self._lock:
            self._data = {"version": 1, "dirs": {}}
            self._dirty_dirs.clear()
            try:
                if FILE_DB_PATH.exists():
                    FILE_DB_PATH.unlink()
                    logger.info("文件列表数据库已删除")
            except OSError as e:
                logger.error("删除文件列表数据库失败: %s", e)

    def get_stats(self):
        """获取数据库统计信息。

        Returns:
            (目录数, 总文件数) 元组
        """
        with self._lock:
            dirs = self._data.get("dirs", {})
            dir_count = len(dirs)
            file_count = sum(
                len(d.get("files", [])) for d in dirs.values()
            )
            return dir_count, file_count
