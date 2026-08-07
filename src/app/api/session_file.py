"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import time
from typing import Any
from urllib.parse import urljoin

import requests

from .constants import BASE_URL
from .download_url import resolve_download_url, rewrite_download_url
from .model import (
    ApiCode,
    ApiReturnModel,
    FileItemModel,
    FileListResponse,
)


class FileSessionMixin:
    """文件与目录 API（mixin，不定义 __init__）。"""

    # ---- 文件列表 ----

    def get_file_list(
        self,
        file_id: int = 0,
        reverse: bool = False,
        trashed: bool = False,
        page: int = 1,
        limit: int = 100,
        retry_login: bool = True,
    ) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/api/file/list/new")
        params = {
            "driveId": 0,
            "limit": limit,
            "next": 0,
            "orderBy": "file_id",
            "orderDirection": "asc" if reverse else "desc",
            "parentFileId": str(file_id),
            "trashed": str(trashed).lower(),
            "SearchData": "",
            "Page": str(page),
            "OnlyLookAbnormalFile": 0,
        }
        t0 = time.monotonic()
        try:
            resp = self._http.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            logger.error(
                "获取文件列表失败 (%.2fs): file_id=%s, page=%s, err=%s",
                time.monotonic() - t0,
                file_id,
                page,
                e,
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            logger.error(
                "文件列表响应异常: file_id=%s, HTTP %s", file_id, resp.status_code
            )
            return error
        code = body.get("code", -1)
        total = (
            body.get("data", {}).get("Total", 0)
            if isinstance(body.get("data"), dict)
            else 0
        )
        logger.debug(
            "获取文件列表 (%.2fs): file_id=%s, page=%s, code=%s, total=%s",
            elapsed,
            file_id,
            page,
            code,
            total,
        )
        if code == 2 and retry_login:
            logger.warning("token 过期，需重新登录: file_id=%s", file_id)
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", "token 过期"),
            )
        if code != 0:
            logger.error(
                "获取文件列表失败: file_id=%s, code=%s, msg=%s",
                file_id,
                code,
                body.get("message", ""),
            )
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        try:
            file_list_response = FileListResponse.from_dict(body)
        except Exception as e:
            logger.error("解析文件列表失败: %s", e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=f"解析响应失败: {e}",
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=file_list_response,
        )

    def get_trash_list(self, file_id: int = 0) -> ApiReturnModel:
        return self.get_file_list(file_id=file_id, trashed=True)

    # ---- 文件夹操作 ----

    def create_dir(self, dir_name: str, parent_file_id: int) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/upload_request")
        data = {
            "driveId": 0,
            "etag": "",
            "fileName": dir_name,
            "parentFileId": parent_file_id,
            "size": 0,
            "type": 1,
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error(
                "创建文件夹失败: name=%s, parent=%s, err=%s",
                dir_name,
                parent_file_id,
                e,
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "创建文件夹 (%.2fs): name=%s, parent=%s, code=%s",
            elapsed,
            dir_name,
            parent_file_id,
            code,
        )
        if code != 0:
            logger.error(
                "创建文件夹失败: name=%s, code=%s, msg=%s",
                dir_name,
                code,
                body.get("message", ""),
            )
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=body.get("data"),
        )

    # ---- 删除/恢复 ----

    def trash_file(
        self, file_info: dict | FileItemModel, operation: bool = True
    ) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/trash")
        if isinstance(file_info, FileItemModel):
            payload = file_info.to_json()
        else:
            payload = file_info
        data = {
            "driveId": 0,
            "fileTrashInfoList": payload,
            "operation": operation,
        }
        op_name = "删除" if operation else "恢复"
        file_name = (
            payload.get("FileName", payload.get("fileName", "?"))
            if isinstance(payload, dict)
            else "?"
        )
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error("%s文件失败: name=%s, err=%s", op_name, file_name, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "%s文件 (%.2fs): name=%s, code=%s", op_name, elapsed, file_name, code
        )
        if code != 0:
            logger.error(
                "%s文件失败: name=%s, code=%s, msg=%s",
                op_name,
                file_name,
                code,
                body.get("message", ""),
            )
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg=body.get("message", ""),
        )

    def restore_file(self, file_info: dict | FileItemModel) -> ApiReturnModel:
        return self.trash_file(file_info, operation=False)

    def trash_delete(self, file_id_list: list[int]) -> ApiReturnModel:
        """从回收站永久删除指定文件。

        Args:
            file_id_list: 要永久删除的文件 ID 列表

        Returns:
            ApiReturnModel
        """
        url = "https://api.123278.com/b/api/file/delete"
        data = {
            "fileIdList": [{"fileId": fid} for fid in file_id_list],
            "event": "recycleDelete",
            "operatePlace": 1,
            "RequestSource": None,
        }
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error("永久删除请求失败: file_ids=%s, err=%s", file_id_list, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        msg = body.get("message", "")
        logger.debug(
            "永久删除 (%.2fs): file_ids=%s, code=%s, msg=%s",
            elapsed, file_id_list, code, msg,
        )
        if code != 0:
            logger.warning(
                "永久删除: file_ids=%s, code=%s, msg=%s",
                file_id_list, code, msg,
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg=msg,
        )

    # ---- 下载链接 ----

    # 下载流量限制错误码（返回时需走 URL 重写绕过）
    _DOWNLOAD_LIMIT_CODES = frozenset({5113, 5114})

    def get_file_link(
        self, file_info: dict | FileItemModel
    ) -> ApiReturnModel:  # pylint: disable=protected-access
        if isinstance(file_info, FileItemModel):
            type_val = file_info._type  # pylint: disable=protected-access
        else:
            type_val = file_info.get("Type", file_info.get("type", 0))

        request_data: dict[str, Any]
        if type_val == 1:
            url = urljoin(BASE_URL, "/a/api/file/batch_download_info")
            if isinstance(file_info, FileItemModel):
                file_id = file_info.file_id
            else:
                file_id = int(file_info.get("FileId", file_info.get("fileId", 0)))
            request_data = {"fileIdList": [{"fileId": file_id}]}
        else:
            url = urljoin(BASE_URL, "/a/api/file/download_info")
            if isinstance(file_info, FileItemModel):
                request_data = {
                    "driveId": 0,
                    "etag": file_info.etag,
                    "fileId": file_info.file_id,
                    "s3keyFlag": file_info.s3key_flag,
                    "type": file_info._type,  # pylint: disable=protected-access
                    "fileName": file_info.file_name,
                    "size": file_info.size,
                }
            else:
                request_data = {
                    "driveId": 0,
                    "etag": file_info.get("Etag", file_info.get("etag", "")),
                    "fileId": file_info.get("FileId", file_info.get("fileId", 0)),
                    "s3keyFlag": file_info.get(
                        "S3KeyFlag", file_info.get("s3keyFlag", "")
                    ),
                    "type": file_info.get("Type", file_info.get("type", 0)),
                    "fileName": file_info.get(
                        "FileName", file_info.get("fileName", "")
                    ),
                    "size": file_info.get("Size", file_info.get("size", 0)),
                }
        file_name = request_data.get("fileName", "?")
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=request_data, timeout=10)
        except requests.RequestException as e:
            logger.error("获取下载链接失败: name=%s, err=%s", file_name, e)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "获取下载链接 (%.2fs): name=%s, type=%s, code=%s",
            elapsed,
            file_name,
            type_val,
            code,
        )
        if code != 0:
            # 5113/5114: 下载流量已超出限制
            if code in self._DOWNLOAD_LIMIT_CODES:
                logger.warning(
                    "下载流量已超出限制 (code=%s)，已绕过拦截: name=%s", code, file_name
                )
                # 不返回错误，继续执行 URL 重写绕过
            else:
                logger.error(
                    "获取下载链接失败: name=%s, code=%s, msg=%s",
                    file_name,
                    code,
                    body.get("message", ""),
                )
                return ApiReturnModel(
                    code=code,
                    api_code=code,
                    api_code_enum=ApiCode.fail,
                    msg=body.get("message", ""),
                )
        data = body.get("data") or {}

        # API 可能直接返回已解析的 CDN 下载链接（redirect_url）
        redirect_url = data.get("RedirectUrl", data.get("redirect_url", ""))
        if redirect_url:
            logger.info(
                "下载链接已获取（直链）: name=%s, size=%s",
                file_name,
                request_data.get("size", "?"),
            )
            return ApiReturnModel(
                code=0,
                api_code=200,
                api_code_enum=ApiCode.success,
                msg="",
                data=redirect_url,
            )

        # 否则使用 DownloadUrl 并通过 web-pro2 代理重写
        download_url = data.get("DownloadUrl", data.get("downloadUrl", ""))
        if not download_url:
            logger.error("响应中未找到下载链接: name=%s", file_name)
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg="响应中未找到下载链接",
            )

        # 模拟 123pan_unlock.js: 重写下载 URL 绕过限制
        rewritten_url = rewrite_download_url(download_url)
        redirect_url = resolve_download_url(self._transfer, rewritten_url)
        logger.info(
            "下载链接已获取: name=%s, size=%s", file_name, request_data.get("size", "?")
        )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
            data=redirect_url,
        )

    # ---- 重命名 ----

    def rename_file(self, file_id: int, new_name: str) -> ApiReturnModel:
        url = urljoin(BASE_URL, "/a/api/file/rename")
        data = {"driveId": 0, "fileId": file_id, "fileName": new_name}
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error(
                "重命名失败: file_id=%s, new_name=%s, err=%s", file_id, new_name, e
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "重命名 (%.2fs): file_id=%s, new_name=%s, code=%s",
            elapsed,
            file_id,
            new_name,
            code,
        )
        if code != 0:
            logger.error(
                "重命名失败: file_id=%s, code=%s, msg=%s",
                file_id,
                code,
                body.get("message", ""),
            )
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
        )

    def mod_pid(self, file_id_list: list[int], target_parent_id: int) -> ApiReturnModel:
        """移动文件/文件夹到目标目录。

        调用 /b/api/file/mod_pid 接口。
        """
        url = urljoin(BASE_URL, "/b/api/file/mod_pid")
        data = {
            "fileIdList": [{"FileId": int(fid)} for fid in file_id_list],
            "parentFileId": int(target_parent_id),
        }
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error(
                "移动文件失败: target=%s, n=%d, err=%s",
                target_parent_id,
                len(file_id_list),
                e,
            )
            return ApiReturnModel(
                code=-1,
                api_code=-1,
                api_code_enum=ApiCode.fail,
                msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.debug(
            "移动文件 (%.2fs): target=%s, n=%d, code=%s",
            elapsed,
            target_parent_id,
            len(file_id_list),
            code,
        )
        if code != 0:
            logger.error(
                "移动文件失败: target=%s, code=%s, msg=%s",
                target_parent_id,
                code,
                body.get("message", ""),
            )
            return ApiReturnModel(
                code=code,
                api_code=code,
                api_code_enum=ApiCode.fail,
                msg=body.get("message", ""),
            )
        return ApiReturnModel(
            code=0,
            api_code=200,
            api_code_enum=ApiCode.success,
            msg="",
        )


from ..common.log import get_logger  # noqa: E402  (模块底部导入，避免循环依赖)

logger = get_logger(__name__)
