"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import time
from pathlib import Path

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

    def show(self, file_list_len, total, all_file):
        """显示文件列表信息到日志。"""
        if not all_file:
            logger.info("获取了%d/%d个文件", file_list_len, total)
        else:
            logger.info("获取全部%d个文件", file_list_len)

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

    def delete_file_by_id(self, file_id, parent_file_id):
        """按文件ID删除文件（无需外部 file_list）。"""
        code, items, *_ = self.get_dir_by_id(parent_file_id, all=True, limit=1000)
        if code != 0:
            return False, "获取文件列表失败"
        for item in items:
            if str(item.get("FileId")) == str(file_id):
                return self.delete_file(items, item, by_num=False, operation=True)
        return False, "文件未找到"

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

    def get_all_things(self, file_id, dir_ids, file_list, name_dict):
        """递归获取文件夹内所有内容。

        Returns:
            (file_list, dir_ids, name_dict) 更新后的状态
        """
        dir_ids.discard(file_id)
        code, items, *_ = self.get_dir_by_id(file_id, all=True, limit=100)
        if code != 0:
            return file_list, dir_ids, name_dict

        for item in items:
            if item["Type"] == 0:
                file_list.append(item)
            else:
                dir_ids.add(item["FileId"])
                name_dict[item["FileId"]] = item["FileName"]

        for did in list(dir_ids):
            if did != file_id:
                file_list, dir_ids, name_dict = self.get_all_things(
                    did, dir_ids, file_list, name_dict
                )

        return file_list, dir_ids, name_dict

    def download_dir(self, file_detail, file_list, name_dict, download_path_root="download"):
        """下载文件夹（递归）。使用 file_list 中的 DownloadUrl。"""
        name_dict[file_detail["FileId"]] = file_detail["FileName"]
        if file_detail["Type"] != 1:
            logger.warning("不是文件夹")
            return

        code, items, *_ = self.get_dir_by_id(
            file_detail["FileId"], all=True, limit=100
        )
        if code != 0:
            return

        for item in reversed(items):
            if item["Type"] == 0:
                abs_path = item["AbsPath"]
                for key, value in name_dict.items():
                    abs_path = abs_path.replace(str(key), value)
                download_path = download_path_root + abs_path
                download_path = download_path.replace("/" + str(item["FileId"]), "")
                self._download_from_url(
                    item["DownloadUrl"], item["FileName"], download_path
                )
            else:
                self.download_dir(item, file_list, name_dict, download_path_root)

    def _download_from_url(self, url, file_name, download_path):
        """从URL下载文件到指定路径。"""
        download_dir = Path(download_path)
        if not download_dir.exists():
            logger.info("创建下载目录")
            download_dir.mkdir(parents=True, exist_ok=True)

        file_path = download_dir / file_name
        temp_path = file_path.with_suffix(file_path.suffix + ".123pan")

        if temp_path.exists():
            temp_path.unlink()

        resp = self._session.transfer.get(url, stream=True, timeout=10)
        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        temp_path.rename(file_path)
