"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from pathlib import Path

from ..common.log import get_logger
from ..common.sync_store import SyncStore
from .file_service import FileService
from .upload_service import UploadService

logger = get_logger(__name__)

# 进度阶段标识
PHASE_SCAN_LOCAL = "scan_local"
PHASE_SCAN_REMOTE = "scan_remote"
PHASE_UPLOAD = "upload"
PHASE_DELETE = "delete"


class SyncService:
    """文件夹同步服务。

    将本地目录（含子目录）增量同步到 123 云盘指定目录。
    - 方向：仅本地上传到云端（upload）
    - 变更检测：文件指纹（size + mtime），指纹存在时同尺寸修改也能识别
    - 可选：本地删除时同步删除云端多余文件
    - 不持有 Qt 依赖，可由后台线程调用
    """

    def __init__(self, session, account_name=None):
        self._session = session
        self._upload = UploadService(session)
        self._file = FileService(session, account_name)
        self._store = SyncStore()

    def set_account(self, account_name):
        self._file.set_account(account_name)

    # ---- 索引构建 ----

    def build_local_index(self, local_root):
        """扫描本地目录树。

        Args:
            local_root: 本地目录路径

        Returns:
            {rel_path: {"size": int, "mtime": int, "abs": str, "is_dir": bool}}
            rel_path 使用 '/' 分隔，根目录相对路径为空字符串。
        """
        root = Path(local_root)
        index = {}
        if not root.exists() or not root.is_dir():
            logger.warning("同步本地路径不存在或不是目录: %s", local_root)
            return index

        for dirpath, dirnames, filenames in os.walk(root):
            # 不进入符号链接目录，避免同步根目录之外的内容。
            dirnames[:] = [
                name for name in dirnames
                if not (Path(dirpath) / name).is_symlink()
            ]
            dir_rel = os.path.relpath(dirpath, root)
            dir_rel = "" if dir_rel == "." else dir_rel.replace(os.sep, "/")

            for d in dirnames:
                full = Path(dirpath) / d
                rel = f"{dir_rel}/{d}" if dir_rel else d
                try:
                    st = full.stat()
                except OSError:
                    continue
                index[rel] = {
                    "size": 0,
                    "mtime": int(st.st_mtime),
                    "abs": str(full),
                    "is_dir": True,
                }

            for f in filenames:
                full = Path(dirpath) / f
                # 符号链接文件可能指向同步根目录之外，禁止上传其目标内容。
                if full.is_symlink():
                    continue
                rel = f"{dir_rel}/{f}" if dir_rel else f
                try:
                    st = full.stat()
                except OSError:
                    continue
                if not full.is_file():
                    continue
                index[rel] = {
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "abs": str(full),
                    "is_dir": False,
                }
        return index

    def build_remote_index(self, remote_dir_id):
        """递归获取云端目录树（强制刷新，保证对比数据最新）。

        Args:
            remote_dir_id: 云端目标目录 ID（0 表示根目录）

        Returns:
            {rel_path: 云端文件/目录 item dict}，rel_path 以 '/' 分隔。
            获取失败（网络/token 过期等）返回 None，调用方必须中止同步
            ——否则会把远端误判为空目录，导致误传/误删。
        """
        index = {}
        ok = self._build_remote_recursive(int(remote_dir_id), "", index)
        return index if ok else None

    def _build_remote_recursive(self, dir_id, rel_dir, index):
        code, items, *_ = self._file.get_dir_by_id(
            dir_id, all=True, limit=100, force_refresh=True
        )
        if code != 0:
            logger.error("获取云端目录失败: dir_id=%s, code=%s", dir_id, code)
            return False
        for item in items:
            name = item.get("FileName", "")
            if not name:
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            index[rel] = item
            if int(item.get("Type", 0)) == 1:
                if not self._build_remote_recursive(item["FileId"], rel, index):
                    return False
        return True

    # ---- 变更计算 ----

    def compute_changes(self, job, local_index, remote_index):
        """对比本地/云端索引与指纹，生成同步计划。

        Args:
            job: sync_jobs 行（dict）
            local_index: build_local_index 的结果
            remote_index: build_remote_index 的结果

        Returns:
            (uploads, dirs_to_create, deletes)
            - uploads: [(rel_path, abs_path, parent_rel, is_new)]
            - dirs_to_create: [(rel_path, parent_rel)]
            - deletes: [rel_path]（仅当 delete_remote 开启）
        """
        job_id = int(job["id"])
        delete_remote = bool(job.get("delete_remote"))
        fingerprints = self._store.get_fingerprints(job_id)

        uploads = []
        dirs_to_create = []

        for rel, info in local_index.items():
            parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""

            if info["is_dir"]:
                # 本地目录在云端缺失 → 需要创建
                if rel not in remote_index:
                    dirs_to_create.append((rel, parent_rel))
                continue

            remote = remote_index.get(rel)
            fp = fingerprints.get(rel)

            if fp is not None:
                # 已有指纹：指纹一致且云端存在 → 已同步，跳过
                if fp == (info["size"], info["mtime"]):
                    if remote is None:
                        # 云端被删除（或目录冲突），重新上传
                        uploads.append((rel, info["abs"], parent_rel, True))
                    continue
                # 指纹变化 → 内容/时间已变，重新上传
                uploads.append((rel, info["abs"], parent_rel, remote is None))
                continue

            # 首次同步：云端大小一致视为已同步（记录指纹，跳过上传）
            if remote is not None and int(remote.get("Size", 0) or 0) == info["size"]:
                self._store.set_fingerprint(
                    job_id, rel, info["size"], info["mtime"]
                )
                continue

            uploads.append((rel, info["abs"], parent_rel, remote is None))

        deletes = []
        if delete_remote:
            for rel in remote_index:
                if rel not in local_index:
                    deletes.append(rel)

        return uploads, dirs_to_create, deletes

    # ---- 执行 ----

    def run_sync(self, job, progress_callback=None, cancel=None):
        """执行一次完整同步。

        Args:
            job: sync_jobs 行（dict）
            progress_callback: 可选 (rel_path, current, total, phase)，
                阶段为扫描时 rel_path 为 None
            cancel: 可选对象，具备 is_cancelled 属性

        Returns:
            (success, stats)，stats = {"added","updated","deleted","failed","skipped"}
        """
        job_id = int(job["id"])
        local_root = job["local_path"]
        remote_root = int(job["remote_dir_id"])
        stats = {"added": 0, "updated": 0, "deleted": 0, "failed": 0, "skipped": 0}

        def _cancelled():
            return cancel is not None and getattr(cancel, "is_cancelled", False)

        if _cancelled():
            return False, stats

        # 安全校验：本地目录必须存在，避免误删云端数据
        if not os.path.isdir(local_root):
            logger.error("同步本地目录不存在或不可访问: %s", local_root)
            return False, stats

        # 1. 本地索引
        if progress_callback:
            progress_callback(None, 0, 0, PHASE_SCAN_LOCAL)
        local_index = self.build_local_index(local_root)

        # 2. 云端索引（失败必须中止，防止误传/误删）
        if progress_callback:
            progress_callback(None, 0, 0, PHASE_SCAN_REMOTE)
        remote_index = self.build_remote_index(remote_root)
        if remote_index is None:
            logger.error("获取云端目录失败，中止同步: dir_id=%s", remote_root)
            return False, stats

        # 3. 变更计划
        uploads, dirs_to_create, deletes = self.compute_changes(
            job, local_index, remote_index
        )
        logger.info(
            "同步计划: job=%s, 上传=%d, 新建目录=%d, 删除=%d, 已同步=%d",
            job.get("name"), len(uploads), len(dirs_to_create),
            len(deletes), stats["skipped"],
        )

        # 4. 创建缺失的云端目录（顶层优先）
        dir_id_map = {rel: item["FileId"] for rel, item in remote_index.items()
                      if int(item.get("Type", 0)) == 1}
        dir_id_map[""] = remote_root
        dirs_to_create.sort(key=lambda x: x[0].count("/"))
        for rel, parent_rel in dirs_to_create:
            if _cancelled():
                return False, stats
            parent_id = dir_id_map.get(parent_rel)
            if parent_id is None:
                logger.error("同步建目录失败，父目录缺失: %s", rel)
                stats["failed"] += 1
                continue
            name = rel.rsplit("/", 1)[-1]
            fid, err = self._file.create_folder(name, parent_id)
            if fid is None:
                logger.error("同步建目录失败: %s (%s)", rel, err)
                stats["failed"] += 1
                continue
            dir_id_map[rel] = fid
            remote_index.setdefault(rel, {"FileId": fid, "Type": 1})
            logger.debug("同步已创建云端目录: %s", rel)

        # 5. 上传文件
        total = len(uploads)
        for i, (rel, abs_path, parent_rel, is_new) in enumerate(uploads, start=1):
            if _cancelled():
                return False, stats
            parent_id = dir_id_map.get(parent_rel)
            if parent_id is None:
                logger.error("同步上传失败，父目录缺失: %s", rel)
                stats["failed"] += 1
                continue
            if progress_callback:
                progress_callback(rel, i, total, PHASE_UPLOAD)
            try:
                # 新文件：duplicate=0；更新覆盖：duplicate=2
                dup_choice = 2 if not is_new else 0
                result = self._upload.up_load(abs_path, parent_id, dup_choice=dup_choice)
                if result == "已取消":
                    return False, stats
                if is_new:
                    stats["added"] += 1
                else:
                    stats["updated"] += 1
                info = local_index[rel]
                self._store.set_fingerprint(job_id, rel, info["size"], info["mtime"])
            except Exception as e:
                logger.error("同步上传失败: %s (%s)", rel, e)
                stats["failed"] += 1

        # 6. 删除云端多余条目（仅当 delete_remote 开启），文件优先、目录自底向上
        if deletes:
            file_dels = [r for r in deletes
                         if int(remote_index[r].get("Type", 0)) == 0]
            dir_dels = sorted(
                (r for r in deletes if int(remote_index[r].get("Type", 0)) == 1),
                key=lambda x: -x.count("/"),
            )
            for rel in file_dels + dir_dels:
                if _cancelled():
                    return False, stats
                if progress_callback:
                    progress_callback(rel, 0, 0, PHASE_DELETE)
                try:
                    result = self._session.trash_file(remote_index[rel], operation=True)
                    if result.code == 0:
                        stats["deleted"] += 1
                        self._store.remove_fingerprint(job_id, rel)
                    else:
                        logger.warning("同步删除失败: %s (code=%s)", rel, result.code)
                        stats["failed"] += 1
                except Exception as e:
                    logger.error("同步删除异常: %s (%s)", rel, e)
                    stats["failed"] += 1

        # 同步可能改变了云端结构，标记缓存失效
        self._file.mark_all_dirs_dirty()

        logger.info(
            "同步完成: job=%s, 新增=%d, 更新=%d, 删除=%d, 失败=%d",
            job.get("name"), stats["added"], stats["updated"],
            stats["deleted"], stats["failed"],
        )
        return True, stats
