"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import hashlib
import time
from pathlib import Path

from ..common.log import get_logger
from ..common.speed_limiter import SpeedLimiter

logger = get_logger(__name__)


class UploadService:
    """上传服务。

    处理文件上传流程，支持基础/流式上传及进度回调。
    """

    def __init__(self, session):
        self._session = session
        # 上传限速器由本服务持有并消费（下载限速器由 session 持有）
        self._limiter = None

    def set_upload_speed_limit(self, kbps: int):
        """设置上传速度限制（KB/s），0 为不限速。

        限速器属于上传服务自身：上传分片循环在
        up_load 中对每个分片消费令牌，0 表示不限制。
        """
        if kbps > 0:
            self._limiter = SpeedLimiter(kbps)
        else:
            self._limiter = None

    @staticmethod
    def compute_file_md5(file_path):
        """计算文件MD5值。"""
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(64 * 1024)
                if not data:
                    break
                md5.update(data)
        return md5.hexdigest()

    def _validate_resume_info(self, resume_info, file_path_obj, fsize):
        """校验续传信息是否可用于当前文件。

        Returns:
            有效时返回 resume_info dict，否则返回 None。
        """
        if not resume_info or not isinstance(resume_info, dict):
            return None
        required = ("bucket", "storage_node", "upload_key", "upload_id", "up_file_id")
        if not all(resume_info.get(k) for k in required):
            return None
        if resume_info.get("file_size") != fsize:
            return None
        # 文件修改时间变化则放弃续传
        stored_mtime = resume_info.get("file_mtime")
        current_mtime = file_path_obj.stat().st_mtime
        if stored_mtime and abs(stored_mtime - current_mtime) > 1:
            return None
        return resume_info

    def up_load(
        self, file_path, parent_file_id, dup_choice=0, signals=None, task=None,
        resume_info=None, session_callback=None,
    ):
        """上传文件（支持断点续传）。

        Args:
            file_path: 本地文件路径
            parent_file_id: 目标目录ID
            dup_choice: 重复文件处理策略（0=提示/1=覆盖/2=跳过）
            signals: 可选信号对象（需有 progress 信号）
            task: 可选的任务控制对象（需有 is_cancelled 属性）
            resume_info: 断点续传信息（S3 会话），文件未变化时复用
            session_callback: 获得 S3 会话后回调，供调用方持久化续传信息

        Returns:
            int: 上传后的文件ID（成功）
            str: "已取消" 如果被取消
        """
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_path_obj = Path(file_path)
        file_name = file_path_obj.name
        if not file_path_obj.exists():
            raise FileNotFoundError("文件不存在")
        if file_path_obj.is_dir():
            raise IsADirectoryError("不支持文件夹上传")
        fsize = file_path_obj.stat().st_size
        logger.info("上传开始: %s (%.2f MB)", file_name, fsize / 1024 / 1024)

        t0 = time.monotonic()
        block_size = 5242880

        if task and task.is_cancelled:
            return "已取消"

        # 校验续传信息：文件未变化时复用既有 S3 会话
        resume = self._validate_resume_info(resume_info, file_path_obj, fsize)

        if resume:
            bucket = resume["bucket"]
            storage_node = resume["storage_node"]
            upload_key = resume["upload_key"]
            upload_id = resume["upload_id"]
            up_file_id = resume["up_file_id"]
            logger.info("上传断点续传: %s (upload_id=%s)", file_name, upload_id)
        else:
            readable_hash = self.compute_file_md5(file_path)
            logger.debug("文件 MD5 计算完成: %s", readable_hash)

            list_up_request = {
                "driveId": 0,
                "etag": readable_hash,
                "fileName": file_name,
                "parentFileId": parent_file_id,
                "size": fsize,
                "type": 0,
                "duplicate": 0,
            }

            up_res = self._session.http.post(
                "https://www.123pan.cn/b/api/file/upload_request",
                json=list_up_request,
                timeout=30,
            )
            up_res_json = up_res.json()
            res_code_up = up_res_json.get("code", -1)
            if res_code_up == 5060:
                list_up_request["duplicate"] = dup_choice
                up_res = self._session.http.post(
                    "https://www.123pan.cn/b/api/file/upload_request",
                    json=list_up_request,
                    timeout=30,
                )
                up_res_json = up_res.json()
                res_code_up = up_res_json.get("code", -1)
            if res_code_up != 0:
                raise RuntimeError(f"上传请求失败: {up_res_json}")

            if up_res_json["data"].get("Reuse", False):
                up_file_id = up_res_json["data"]["FileId"]
                elapsed = time.monotonic() - t0
                speed = fsize / 1024 / 1024 / elapsed if elapsed > 0 else 0
                logger.info(
                    "上传完成(复用): %s (%.2f MB / %.1fs / %.1f MB/s)",
                    file_name, fsize / 1024 / 1024, elapsed, speed,
                )
                return up_file_id

            bucket = up_res_json["data"]["Bucket"]
            storage_node = up_res_json["data"]["StorageNode"]
            upload_key = up_res_json["data"]["Key"]
            upload_id = up_res_json["data"]["UploadId"]
            up_file_id = up_res_json["data"]["FileId"]

            # 回调持久化 S3 会话，供中断后断点续传
            if session_callback:
                try:
                    session_callback(
                        {
                            "bucket": bucket,
                            "storage_node": storage_node,
                            "upload_key": upload_key,
                            "upload_id": upload_id,
                            "up_file_id": up_file_id,
                            "etag": readable_hash,
                            "file_mtime": file_path_obj.stat().st_mtime,
                            "file_size": fsize,
                            "block_size": block_size,
                        }
                    )
                except Exception as e:
                    logger.error("持久化上传会话失败: %s", e)

        start_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        start_res = self._session.http.post(
            "https://www.123pan.cn/b/api/file/s3_list_upload_parts",
            json=start_data,
            timeout=30,
        )
        start_res_json = start_res.json()
        res_code_up = start_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"获取传输列表失败: {start_res_json}")

        # 已上传分片（续传时跳过）
        uploaded_parts = set()
        for part in (start_res_json.get("data") or {}).get("parts") or []:
            try:
                uploaded_parts.add(int(part.get("PartNumber", 0)))
            except (TypeError, ValueError):
                pass

        part_number = 1
        while part_number in uploaded_parts:
            part_number += 1
        total_sent = min((part_number - 1) * block_size, fsize)
        if part_number > 1:
            logger.info("上传续传跳过 %d 个已完成分片", part_number - 1)

        with open(file_path, "rb") as f:
            if part_number > 1:
                f.seek((part_number - 1) * block_size)
            while True:
                if task and task.is_cancelled:
                    return "已取消"

                data = f.read(block_size)
                if not data:
                    break

                # 暂停：阻塞等待恢复；取消：立即中止（保留已上传分片供续传）
                if task:
                    waiter = getattr(task, "wait_if_paused", None)
                    if waiter is not None:
                        waiter()
                    if getattr(task, "is_cancelled", False):
                        return "已取消"

                # 上传限速：消费当前分片的令牌并等待
                if self._limiter:
                    wait = self._limiter.consume(len(data))
                    if wait > 0:
                        time.sleep(wait)

                get_link_data = {
                    "bucket": bucket,
                    "key": upload_key,
                    "partNumberEnd": part_number + 1,
                    "partNumberStart": part_number,
                    "uploadId": upload_id,
                    "StorageNode": storage_node,
                }
                get_link_res = self._session.http.post(
                    "https://www.123pan.cn/b/api/file/s3_repare_upload_parts_batch",
                    json=get_link_data,
                    timeout=30,
                )
                get_link_res_json = get_link_res.json()
                res_code_up = get_link_res_json.get("code", -1)
                if res_code_up != 0:
                    raise RuntimeError(f"获取链接失败: {get_link_res_json}")
                upload_url = get_link_res_json["data"]["presignedUrls"][
                    str(part_number)
                ]
                self._session.transfer.put(upload_url, data=data, timeout=60)
                total_sent += len(data)
                if signals and fsize:
                    signals.progress.emit(int(total_sent * 100 / fsize))
                part_number += 1

        uploaded_comp_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        self._session.http.post(
            "https://www.123pan.cn/b/api/file/s3_list_upload_parts",
            json=uploaded_comp_data,
            timeout=30,
        )
        self._session.http.post(
            "https://www.123pan.cn/b/api/file/s3_complete_multipart_upload",
            json=uploaded_comp_data,
            timeout=30,
        )

        if fsize > 64 * 1024 * 1024:
            time.sleep(3)

        close_up_session_data = {"fileId": up_file_id}
        close_res = self._session.http.post(
            "https://www.123pan.cn/b/api/file/upload_complete",
            json=close_up_session_data,
            timeout=30,
        )
        close_res_json = close_res.json()
        res_code_up = close_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"上传完成确认失败: {close_res_json}")

        elapsed = time.monotonic() - t0
        speed = fsize / 1024 / 1024 / elapsed if elapsed > 0 else 0
        logger.info(
            "上传完成: %s (%.2f MB / %.1fs / %.1f MB/s)",
            file_name, fsize / 1024 / 1024, elapsed, speed,
        )
        return up_file_id
