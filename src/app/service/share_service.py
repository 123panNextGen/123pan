"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import time

import requests

from ..api.model import ApiCode, ApiReturnModel, ShareListResponse
from ..common.log import get_logger

logger = get_logger(__name__)

SHARE_API_BASE = "https://api.123278.com"


class ShareService:
    """分享链接管理服务。

    处理免费分享和付费分享列表的获取。
    """

    def __init__(self, session):
        self._session = session

    def get_free_share_list(self, drive_id=0, limit=500, next_marker=0,
                            order_by="fileId", order_direction="desc",
                            search_data="", operate_type=1):
        """获取免费分享列表。

        Returns:
            ApiReturnModel，成功时 data 为 ShareListResponse 实例
        """
        url = SHARE_API_BASE + "/b/api/share/list"
        params = {
            "driveId": drive_id,
            "limit": limit,
            "next": next_marker,
            "orderBy": order_by,
            "orderDirection": order_direction,
            "SearchData": search_data,
            "event": "shareListFile",
            "operateType": operate_type,
        }
        t0 = time.monotonic()
        try:
            resp = self._session.http.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            logger.error("获取免费分享列表失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1, api_code=-1, api_code_enum=ApiCode.fail, msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._session._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.info("获取免费分享列表 (%.2fs): code=%s", elapsed, code)
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code, api_code=code, api_code_enum=ApiCode.fail, msg=msg,
            )
        share_data = ShareListResponse.from_dict(body)
        return ApiReturnModel(
            code=0, api_code=0, api_code_enum=ApiCode.success, msg="",
            data=share_data,
        )

    def get_pay_share_list(self, drive_id=0, limit=500, next_marker=0,
                           order_by="fileId", order_direction="desc",
                           search_data="", operate_type=1):
        """获取付费分享列表。

        Returns:
            ApiReturnModel，成功时 data 为 ShareListResponse 实例
        """
        url = SHARE_API_BASE + "/b/api/restful/goapi/v1/share/content/payment/list"
        params = {
            "driveId": drive_id,
            "limit": limit,
            "next": next_marker,
            "orderBy": order_by,
            "orderDirection": order_direction,
            "SearchData": search_data,
            "event": "shareListFile",
            "operateType": operate_type,
        }
        t0 = time.monotonic()
        try:
            resp = self._session.http.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            logger.error("获取付费分享列表失败 (%.2fs): %s", time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1, api_code=-1, api_code_enum=ApiCode.fail, msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._session._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.info("获取付费分享列表 (%.2fs): code=%s", elapsed, code)
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code, api_code=code, api_code_enum=ApiCode.fail, msg=msg,
            )
        share_data = ShareListResponse.from_dict(body)
        return ApiReturnModel(
            code=0, api_code=0, api_code_enum=ApiCode.success, msg="",
            data=share_data,
        )

    def delete_share(self, share_id, drive_id=0):
        """删除分享链接。

        Args:
            share_id: 要删除的分享ID
            drive_id: 云盘ID

        Returns:
            ApiReturnModel
        """
        url = SHARE_API_BASE + "/b/api/share/delete"
        data = {
            "driveId": drive_id,
            "shareInfoList": [{"shareId": share_id}],
            "isPayShare": 0,
            "event": "shareCancel",
            "operatePlace": 2,
        }
        t0 = time.monotonic()
        try:
            resp = self._session.http.post(url, json=data, timeout=10)
        except requests.RequestException as e:
            logger.error("删除分享链接失败 shareId=%s (%.2fs): %s", share_id, time.monotonic() - t0, e)
            return ApiReturnModel(
                code=-1, api_code=-1, api_code_enum=ApiCode.fail, msg=str(e),
            )
        elapsed = time.monotonic() - t0
        body, error = self._session._safe_json(resp)
        if error:
            return error
        code = body.get("code", -1)
        logger.info("删除分享链接 shareId=%s (%.2fs): code=%s", share_id, elapsed, code)
        if code != 0:
            msg = body.get("message", "")
            return ApiReturnModel(
                code=code, api_code=code, api_code_enum=ApiCode.fail, msg=msg,
            )
        return ApiReturnModel(
            code=0, api_code=0, api_code_enum=ApiCode.success, msg="",
            data=body.get("data"),
        )
