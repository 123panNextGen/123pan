"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json

from ..api.constants import OFFLINE_BASE_URL
from ..common.log import get_logger
from .file_service import FileService
from .upload_service import UploadService

logger = get_logger(__name__)

# 离线下载 API 端点
_OFFLINE_RESOLVE_URL = OFFLINE_BASE_URL + "/b/api/v2/offline_download/task/resolve?"
_OFFLINE_SUBMIT_URL = OFFLINE_BASE_URL + "/b/api/v2/offline_download/task/submit?"

# 秒传链接前缀（123FastLink / 秒传 JSON 生成器 共用格式）
_RAPID_LINK_PREFIX = "123FLCPV2$"
# Base62 字母表（etag 短编码用）
_BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class OfflineService:
    """离线下载服务。

    提供两类能力：
    1. 离线下载：解析 URL（http/https/magnet/thunder）→ 选择文件 → 提交任务，
       由 123 云盘服务器后台下载。
    2. 秒传导入：解析 123FastLink / 秒传 JSON 生成器（夸克/天翼等）导出的
       秒传数据（JSON 或文本链接），通过 etag 秒传到 123 云盘，
       实现「兼容其他网盘的数据」。
    """

    def __init__(self, session):
        self._session = session
        self._upload = UploadService(session)
        self._file = FileService(session)

    def set_account(self, account_name):
        self._file.set_account(account_name)

    # ---- 离线下载 ----

    def resolve(self, urls):
        """解析离线下载链接。

        Args:
            urls: 链接文本，多个链接用换行分隔

        Returns:
            list[dict]: 解析结果列表，每项形如
                {url, type, result, name, size, id, hash, file_nums,
                 files, err_code, err_msg}
                result=0 表示解析成功；result=1 表示失败（见 err_code/err_msg）

        Raises:
            RuntimeError: 接口级失败
        """
        resp = self._session.http.post(
            _OFFLINE_RESOLVE_URL,
            json={"urls": urls},
            timeout=30,
        )
        body = resp.json()
        if body.get("code", -1) != 0:
            raise RuntimeError(f"离线下载解析失败: {body.get('message', body)}")
        return (body.get("data") or {}).get("list") or []

    def submit(self, resources):
        """提交离线下载任务。

        Args:
            resources: [{"resource_id": int, "select_file_id": [int, ...]}, ...]

        Returns:
            list[dict]: task_list，每项含 task_id/result 等

        Raises:
            RuntimeError: 接口级失败
        """
        resp = self._session.http.post(
            _OFFLINE_SUBMIT_URL,
            json={"resource_list": resources},
            timeout=30,
        )
        body = resp.json()
        if body.get("code", -1) != 0:
            raise RuntimeError(f"离线下载提交失败: {body.get('message', body)}")
        return (body.get("data") or {}).get("task_list") or []

    # ---- 秒传数据解析 ----

    def parse_rapid_data(self, text):
        """解析秒传数据（JSON 或文本链接）。

        Args:
            text: 秒传 JSON 或文本秒传链接

        Returns:
            list[dict]: [{"path": str, "etag": str, "size": int}, ...]

        Raises:
            ValueError: 无法解析
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("输入为空")
        try:
            data = json.loads(text)
        except ValueError:
            return self._parse_rapid_link(text)
        return self._parse_rapid_json(data)

    def _parse_rapid_json(self, data):
        """解析 JSON 格式秒传数据。"""
        if not isinstance(data, dict):
            raise ValueError("JSON 格式无效")
        files = data.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("JSON 中缺少 files 列表")
        common_path = str(data.get("commonPath", "") or "")
        uses_base62 = bool(data.get("usesBase62EtagsInExport", False))

        result = []
        for f in files:
            if not isinstance(f, dict):
                continue
            path = str(f.get("path", "") or "").strip()
            etag = str(f.get("etag", "") or "").strip()
            try:
                size = int(f.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0
            if uses_base62:
                etag = self._base62_to_hex(etag)
            else:
                etag = etag.lower()
            if not path or not self._is_valid_etag(etag):
                continue
            full_path = (common_path + path) if common_path else path
            result.append({"path": full_path, "etag": etag, "size": size})
        if not result:
            raise ValueError("未解析到有效文件")
        return result

    def _parse_rapid_link(self, text):
        """解析文本秒传链接。

        格式：123FLCPV2$<公共路径>%<etag>#<size>#<path>$...
        兼容旧版无前缀格式（etag#size#path 多行）。
        """
        common_path = ""
        share_file_info = ""

        if text.startswith("123F"):
            prefix = text.split("$")[0]
            rest = text[len(prefix) + 1:]  # 去掉 "prefix$"
            if prefix + "$" != _RAPID_LINK_PREFIX:
                raise ValueError("不支持的秒传链接前缀")
            if "%" not in rest:
                raise ValueError("秒传链接格式无效")
            common_path, share_file_info = rest.split("%", 1)
        else:
            # 旧版格式：无前缀，etag#size#path 每行一个
            share_file_info = text

        common_path = common_path or ""
        result = []
        for item in share_file_info.replace("\r\n", "$").replace("\n", "$").split("$"):
            parts = item.split("#")
            if len(parts) < 3:
                continue
            etag, size_str, path = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not path:
                continue
            if len(etag) == 22:
                etag = self._base62_to_hex(etag)
            else:
                etag = etag.lower()
            if not self._is_valid_etag(etag):
                continue
            try:
                size = int(size_str)
            except (TypeError, ValueError):
                continue
            full_path = (common_path + path) if common_path else path
            result.append({"path": full_path, "etag": etag, "size": size})
        if not result:
            raise ValueError("未解析到有效文件")
        return result

    @staticmethod
    def _is_valid_etag(etag):
        """校验 etag 为 32 位十六进制。"""
        if not etag or len(etag) != 32:
            return False
        return all(c in "0123456789abcdef" for c in etag.lower())

    @staticmethod
    def _base62_to_hex(base62):
        """Base62 字符串转 32 位十六进制（小写）。"""
        n = 0
        for ch in base62:
            n = n * 62 + _BASE62_CHARS.index(ch)
        return format(n, "032x")

    # ---- 秒传导入 ----

    def rapid_transfer(self, files, parent_dir_id, progress_callback=None, cancel=None):
        """秒传导入：创建目录结构并逐个秒传文件。

        Args:
            files: [{"path": str, "etag": str, "size": int}, ...]
            parent_dir_id: 目标根目录 ID
            progress_callback: 可选 (current, total)
            cancel: 可选，具备 is_cancelled 属性的对象

        Returns:
            dict: {"success": [path, ...], "failed": [(path, err_msg), ...]}
        """
        parent_dir_id = int(parent_dir_id)
        # 任务内已知目录缓存：(parent_id, name) -> file_id
        known_dirs = {}
        success = []
        failed = []
        total = len(files)

        def _ensure_folder(name, parent_id):
            key = (parent_id, name)
            if key in known_dirs:
                return known_dirs[key]
            # 已有同名文件夹则复用（合并导入）
            code, items, *_ = self._file.get_dir_by_id(
                parent_id, all=True, limit=100
            )
            if code == 0:
                for item in items:
                    if int(item.get("Type", 0)) == 1 and item.get("FileName") == name:
                        fid = int(item["FileId"])
                        known_dirs[key] = fid
                        return fid
            fid, err = self._file.create_folder(name, parent_id)
            if fid is None:
                logger.error("秒传建目录失败: %s (%s)", name, err)
                return None
            fid = int(fid)
            known_dirs[key] = fid
            return fid

        def _make_parent_dirs(path):
            """创建/复用文件父目录结构，返回父目录 ID；失败返回 None。"""
            if "/" not in path:
                return parent_dir_id
            parent_id = parent_dir_id
            for part in path.rsplit("/", 1)[0].split("/"):
                fid = _ensure_folder(part, parent_id)
                if fid is None:
                    return None
                parent_id = fid
            return parent_id

        for i, f in enumerate(files, start=1):
            if cancel is not None and getattr(cancel, "is_cancelled", False):
                break
            path = f.get("path", "")
            file_name = path.rsplit("/", 1)[-1] if "/" in path else path

            parent_id = _make_parent_dirs(path)
            if parent_id is None:
                failed.append((path, "创建目录失败"))
            else:
                try:
                    fid = self._upload.fast_upload(
                        file_name, int(f.get("size", 0) or 0), f.get("etag", ""),
                        parent_id,
                    )
                    if fid is None:
                        failed.append((path, "网盘中不存在相同文件，无法秒传"))
                    else:
                        success.append(path)
                except Exception as e:
                    logger.error("秒传失败: %s (%s)", path, e)
                    failed.append((path, str(e)))

            if progress_callback:
                progress_callback(i, total)

        # 秒传可能改变了云端结构，标记缓存失效
        if success:
            self._file.mark_all_dirs_dirty()
        return {"success": success, "failed": failed}

    # ---- 秒传数据生成（导出） ----

    def build_rapid_payload(self, files):
        """根据文件信息生成标准秒传数据（JSON + 文本链接）。

        Args:
            files: [{"path": str, "etag": str, "size": int}, ...]
                   path 为完整相对路径（从所选根开始，含目录结构）

        Returns:
            (json_text, link_text)
            json_text: 标准 123pan 秒传 JSON 文本
            link_text: 文本秒传链接（123FLCPV2 格式）

        Raises:
            ValueError: files 为空或缺少有效 etag
        """
        if not files:
            raise ValueError("没有可生成的文件")
        valid = [
            f for f in files
            if f.get("etag") and self._is_valid_etag(str(f["etag"]))
        ]
        if not valid:
            raise ValueError("所选文件缺少有效的 etag，无法生成秒传数据")

        common_path = self._common_path(valid)
        rel_files = []
        for f in valid:
            path = str(f.get("path", ""))
            if common_path and path.startswith(common_path):
                path = path[len(common_path):]
            rel_files.append({
                "path": path,
                "etag": str(f.get("etag", "")).lower(),
                "size": int(f.get("size", 0) or 0),
            })

        total_size = sum(f["size"] for f in rel_files)
        json_data = {
            "scriptVersion": "3.0.3",
            "exportVersion": "1.0",
            "usesBase62EtagsInExport": False,
            "commonPath": common_path,
            "files": [
                {"path": f["path"], "etag": f["etag"], "size": f["size"]}
                for f in rel_files
            ],
            "totalFilesCount": len(rel_files),
            "totalSize": total_size,
        }
        json_text = json.dumps(json_data, ensure_ascii=False, indent=2)

        parts = []
        for f in rel_files:
            safe_path = f["path"].replace("%", "").replace("#", "").replace("$", "")
            parts.append(f"{f['etag']}#{f['size']}#{safe_path}")
        link_text = _RAPID_LINK_PREFIX + common_path + "%" + "$".join(parts)
        return json_text, link_text

    @staticmethod
    def _common_path(files):
        """计算所有文件路径的公共目录前缀（含尾部斜杠）。

        Returns:
            str: 公共目录前缀，如 "folder/sub/"，无公共目录时返回 ""
        """
        dirs = []
        for f in files:
            path = str(f.get("path", ""))
            dirs.append(path.rsplit("/", 1)[0] if "/" in path else "")

        if not dirs or all(d == "" for d in dirs):
            return ""
        common = dirs[0].split("/")
        for d in dirs[1:]:
            parts = d.split("/")
            common = [a for a, b in zip(common, parts) if a == b]
            if not common:
                return ""
        cp = "/".join(common)
        return (cp + "/") if cp else ""
