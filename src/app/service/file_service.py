"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import time

from ..common.file_list_db import FileListDB
from ..common.log import get_logger

logger = get_logger(__name__)

# 全量分页加载时的节流间隔（秒）。
# 仅当 all=True（一次性拉取全部页）时生效，防止大目录瞬时打爆服务器；
# 值越小加载越快，0 表示不节流。普通分页（all=False）不受影响。
_PAGE_THROTTLE_SECONDS = 0.5


class FileService:
    """文件与目录管理服务。

    处理文件列表获取、导航、创建、删除、重命名、回收站等操作。
    不持有可变状态，所有状态由调用方（Pan123）管理。
    """

    def __init__(self, session):
        self._session = session
        self._db = FileListDB()

    def get_dir_by_id(self, file_id, page=0, list_len=0, all=False, limit=100,
                      force_refresh=False):
        """按文件夹ID获取文件列表（支持分页和本地缓存）。

        Args:
            file_id: 文件夹ID
            page: 当前页码（0基）
            list_len: 已加载的文件数量
            all: 是否获取所有文件（仅当缓存不完整时才请求服务器）
            limit: 每页限制数量
            force_refresh: 是否跳过缓存强制从服务器获取

        Returns:
            (code, lists, total, all_file, pages_read)
        """
        # 非强制刷新时，优先使用缓存
        if not force_refresh:
            cached_files, cached_total, cached_all = self._db.get_dir(file_id)
            cache_valid = (
                cached_files is not None
                and not self._db.is_dirty(file_id)
                and not self._db.is_stale(file_id)
            )

            if cache_valid:
                # 缓存有完整数据 → 直接返回，不请求服务器
                if cached_all:
                    logger.debug(
                        "使用完整缓存: file_id=%s, files=%d, total=%d",
                        file_id, len(cached_files), cached_total,
                    )
                    return 0, cached_files, cached_total, True, 1

                # 缓存不完整但调用方不要求全量 → 返回已有缓存
                if not all:
                    logger.debug(
                        "使用部分缓存: file_id=%s, files=%d, total=%d",
                        file_id, len(cached_files), cached_total,
                    )
                    return 0, cached_files, cached_total, False, 1

                # 缓存不完整且调用方要求全量 → 继续请求服务器补全
                logger.debug(
                    "缓存不完整，继续从服务器获取: file_id=%s, cached=%d, total=%d",
                    file_id, len(cached_files), cached_total,
                )

        get_pages = 3
        start_page = page * get_pages + 1
        lists = []

        total = -1
        times = 0
        lenth_now = list_len
        t0 = time.monotonic()

        if all:
            start_page = 1
            lenth_now = 0

        while (lenth_now < total or total == -1) and (times < get_pages or all):
            result = self._session.get_file_list(
                file_id=file_id, page=start_page, limit=limit, retry_login=False
            )
            if result.code == 2:
                # token expired — caller should handle re-login
                logger.warning("token 过期: file_id=%s", file_id)
                return result.code, [], 0, False, times

            if result.code != 0:
                logger.error(
                    "获取文件列表失败: file_id=%s, code=%s, msg=%s",
                    file_id, result.code, result.msg,
                )
                return result.code, [], 0, False, times

            file_list_data = result.data.data
            lists_page = [item.to_json() for item in file_list_data.info_list]
            lists += lists_page
            total = file_list_data.total
            lenth_now += len(lists_page)
            start_page += 1
            times += 1

            logger.debug(
                "分页加载: page=%s, got=%s, total=%s, accumulated=%s",
                start_page - 1, len(lists_page), total, lenth_now,
            )
            # 仅全量加载时做短节流，避免大目录一次性请求过多页
            if all and _PAGE_THROTTLE_SECONDS > 0 and times % 5 == 0:
                logger.debug(
                    "文件夹内文件较多（%s/%s），节流 %.1fs",
                    lenth_now, total, _PAGE_THROTTLE_SECONDS,
                )
                time.sleep(_PAGE_THROTTLE_SECONDS)

        elapsed = time.monotonic() - t0
        logger.info(
            "目录列表加载完成: file_id=%s, total=%s, pages=%s, %.1fs",
            file_id, total, times, elapsed,
        )
        all_file = lenth_now >= total
        if not all_file:
            logger.warning("文件夹内文件过多：%s/%s，未完全加载", lenth_now, total)

        # 更新本地缓存
        if lists:
            self._db.save_dir(file_id, lists, total=total, all_loaded=all_file)

        return 0, lists, total, all_file, times

    def mark_dir_dirty(self, dir_id):
        """标记目录缓存为脏，下次浏览时强制从服务器刷新。

        上传/离线下载等云端内容变更后调用，确保文件列表不显示旧缓存。
        """
        self._db.mark_dirty(dir_id)
        logger.debug("标记目录缓存为脏: %s", dir_id)

    def mkdir(self, dirname, file_list, parent_file_id, remakedir=False):
        """创建文件夹。

        Returns:
            (FileId, error_msg) 成功时 error_msg 为空字符串
        """
        if not remakedir:
            for item in file_list:
                if item["FileName"] == dirname:
                    logger.info("文件夹已存在")
                    return item["FileId"], ""

        result = self._session.create_dir(dirname, parent_file_id)
        if result.code != 0:
            logger.error("创建文件夹失败: %s", result.msg)
            return None, result.msg
        try:
            res_json = result.data
            file_id = res_json["Info"]["FileId"]
            logger.info("创建成功: %s", file_id)
            # 标记缓存为脏，下次访问时重新加载
            self._db.mark_dirty(parent_file_id)
            return file_id, ""
        except Exception as e:
            logger.error("创建文件夹解析失败: %s", e)
            return None, str(e)

    def create_folder(self, dirname, parent_file_id):
        """创建文件夹（简化版，无需 file_list）。"""
        result = self._session.create_dir(dirname, parent_file_id)
        if result.code != 0:
            logger.error("创建文件夹失败: %s", result.msg)
            return None, result.msg
        try:
            res_json = result.data
            file_id = res_json["Info"]["FileId"]
            logger.info("创建成功: %s", file_id)
            return file_id, ""
        except Exception as e:
            logger.error("创建文件夹解析失败: %s", e)
            return None, str(e)

    def delete_file(self, file_list, file, by_num=True, operation=True,
                    parent_file_id=None):
        """删除或恢复文件。返回 (success, msg)。"""
        if by_num:
            if not str(file).isdigit():
                raise ValueError("文件索引必须是数字")
            if 0 <= file < len(file_list):
                file_detail = file_list[file]
            else:
                raise IndexError("文件索引超出范围")
        else:
            if file in file_list:
                file_detail = file
            else:
                raise ValueError("文件不存在")

        result = self._session.trash_file(file_detail, operation=operation)
        logger.debug("删除文件响应: code=%s, msg=%s", result.code, result.msg)
        if result.code != 0:
            logger.error("删除文件失败: %s", result.msg)
            return False, result.msg
        logger.info("删除文件消息: %s", result.msg)
        # 标记缓存为脏
        if parent_file_id is not None:
            self._db.mark_dirty(parent_file_id)
        return True, result.msg

    def rename_file(self, file_id, new_name, parent_file_id=None):
        """重命名文件或文件夹。

        Returns:
            bool: 是否成功
        """
        result = self._session.rename_file(file_id, new_name)
        logger.debug("重命名文件响应: code=%s, msg=%s", result.code, result.msg)
        if result.code != 0:
            logger.error("重命名失败: %s", result.msg)
            return False
        logger.info("重命名成功: %s", new_name)
        # 标记缓存为脏
        if parent_file_id is not None:
            self._db.mark_dirty(parent_file_id)
        return True

    def copy_files(self, file_id_list, target_parent_id, source_parent_id=None):
        """复制文件/文件夹到目标目录。

        Args:
            file_id_list: 文件 ID 列表
            target_parent_id: 目标目录 ID（0 表示根目录）
            source_parent_id: 源目录 ID（用于获取完整文件信息构造 fileList）

        Returns:
            (success, msg)
        """
        if not file_id_list:
            return False, "文件列表为空"

        # 构造 fileList：优先使用源目录列表（含本地缓存）中的完整文件信息
        file_list = []
        by_id = {}
        if source_parent_id is not None:
            code, files, _, _, _ = self.get_dir_by_id(
                source_parent_id, all=True, limit=1000
            )
            if code == 0 and files:
                by_id = {str(f.get("FileId")): f for f in files}
        # 逐项构造：源列表缺失（目录过大/缓存不全）的文件降级为仅 FileId，不静默丢弃
        for fid in file_id_list:
            info = by_id.get(str(fid))
            if info:
                item = dict(info)
                item.setdefault("DriveId", 0)
            else:
                item = {"FileId": int(fid)}
            file_list.append(item)

        result = self._session.copy_files_async(file_list, target_parent_id)
        if result.code != 0:
            logger.error(
                "复制文件失败: target=%s, code=%s, msg=%s",
                target_parent_id, result.code, result.msg,
            )
            return False, result.msg or f"复制失败 (code={result.code})"

        success, msg = self._poll_copy_task(result.data)
        if not success:
            return False, msg
        # 复制后目标目录缓存失效
        self._db.mark_dirty(target_parent_id)
        return True, ""

    def _poll_copy_task(self, task_id, max_retries=60, interval=1.0):
        """轮询复制任务直到终态。返回 (success, msg)。"""
        for _ in range(max_retries):
            result = self._session.copy_file_task(task_id)
            if result.code != 0:
                return False, result.msg or f"查询复制任务失败 (code={result.code})"
            data = result.data or {}
            status = data.get("status")
            if status is None:
                # 防御性兜底：响应不含状态字段时视为成功。
                # 风险：若服务端处理中恰好返回无 status 的响应，会提前报成功，
                # 用户可通过刷新列表核对结果。
                return True, ""
            if status == 2:
                return True, ""
            if status == 3:
                return False, data.get("failMsg") or "复制任务失败"
            # status 1（进行中）/4（等待）继续轮询
            time.sleep(interval)
        return False, "复制超时，请稍后刷新查看结果"

    def move_files(self, file_id_list, target_parent_id):
        """移动文件/文件夹到目标目录。

        Args:
            file_id_list: 文件 ID 列表
            target_parent_id: 目标目录 ID（0 表示根目录）

        Returns:
            (success, msg)
        """
        if not file_id_list:
            return False, "文件列表为空"
        result = self._session.mod_pid(file_id_list, target_parent_id)
        if result.code != 0:
            logger.error(
                "移动文件失败: target=%s, code=%s, msg=%s",
                target_parent_id, result.code, result.msg,
            )
            return False, result.msg or f"移动失败 (code={result.code})"
        logger.info("移动成功: %d 个文件 -> 目录 %s", len(file_id_list), target_parent_id)
        # 移动后源目录与目标目录缓存均失效
        self._db.mark_dirty(target_parent_id)
        return True, ""

    def recycle(self):
        """获取回收站列表。

        Returns:
            list[dict] 回收站文件列表
        """
        result = self._session.get_trash_list()
        if result.code != 0:
            logger.error("获取回收站失败: code=%s, msg=%s", result.code, result.msg)
            return []
        file_list_data = result.data.data
        return [item.to_json() for item in file_list_data.info_list]

    def permanent_delete_files(self, file_id_list):
        """从回收站永久删除指定文件。

        Args:
            file_id_list: 文件 ID 列表

        Returns:
            (success, msg)
        """
        if not file_id_list:
            return False, "文件列表为空"
        result = self._session.trash_delete(file_id_list)
        logger.debug(
            "永久删除响应: file_ids=%s, code=%s, msg=%s",
            file_id_list, result.code, result.msg,
        )
        if result.code != 0:
            logger.error("永久删除失败: %s", result.msg)
            return False, result.msg
        logger.info("已永久删除 %d 个文件", len(file_id_list))
        return True, result.msg

    def share(self, file_id_list, share_pwd=""):
        """创建分享链接。

        Args:
            file_id_list: 文件ID列表
            share_pwd: 分享密码（可选）

        Returns:
            str: 分享URL
        """
        if not file_id_list:
            raise ValueError("文件ID列表为空")
        data = {
            "driveId": 0,
            "expiration": "2099-12-12T08:00:00+08:00",
            "fileIdList": file_id_list,
            "shareName": "123云盘分享",
            "sharePwd": share_pwd or "",
            "event": "shareCreate",
        }
        share_res = self._session.http.post(
            "https://www.123pan.cn/a/api/share/create",
            json=data,
            timeout=10,
        )
        share_res_json = share_res.json()
        if share_res_json.get("code", -1) != 0:
            raise RuntimeError(f"分享失败: {share_res_json.get('message', '')}")
        share_key = share_res_json["data"]["ShareKey"]
        return "https://www.123pan.cn/s/" + share_key
