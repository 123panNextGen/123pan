import hashlib
import json
import time
from pathlib import Path

from ..common.log import get_logger

logger = get_logger(__name__)


class UploadService:
    """上传服务。

    处理文件上传流程，支持基础上传和带进度回调的上传。
    """

    def __init__(self, session):
        self._session = session

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

    def up_load(self, file_path, parent_file_id):
        """上传文件（基础版）。

        Args:
            file_path: 本地文件路径
            parent_file_id: 目标目录ID

        Returns:
            int: 上传后的文件ID（成功）
            Raises: 各类异常（失败）
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
            timeout=10,
        )
        up_res_json = up_res.json()
        res_code_up = up_res_json.get("code", -1)
        if res_code_up == 5060:
            raise RuntimeError("同名文件存在")
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

        start_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        start_res = self._session.http.post(
            "https://www.123pan.cn/b/api/file/s3_list_upload_parts",
            json=start_data,
            timeout=10,
        )
        start_res_json = start_res.json()
        res_code_up = start_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"获取传输列表失败: {start_res_json}")

        block_size = 5242880
        with open(file_path, "rb") as f:
            part_number_start = 1
            while True:
                data = f.read(block_size)
                if not data:
                    break

                get_link_data = {
                    "bucket": bucket,
                    "key": upload_key,
                    "partNumberEnd": part_number_start + 1,
                    "partNumberStart": part_number_start,
                    "uploadId": upload_id,
                    "StorageNode": storage_node,
                }
                get_link_res = self._session.http.post(
                    "https://www.123pan.cn/b/api/file/s3_repare_upload_parts_batch",
                    json=get_link_data,
                    timeout=10,
                )
                get_link_res_json = get_link_res.json()
                res_code_up = get_link_res_json.get("code", -1)
                if res_code_up != 0:
                    raise RuntimeError(f"获取链接失败: {get_link_res_json}")
                upload_url = get_link_res_json["data"]["presignedUrls"][
                    str(part_number_start)
                ]
                self._session.transfer.put(upload_url, data=data, timeout=10)
                part_number_start += 1

        uploaded_list_url = "https://www.123pan.cn/b/api/file/s3_list_upload_parts"
        uploaded_comp_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        self._session.http.post(uploaded_list_url, json=uploaded_comp_data, timeout=10)
        self._session.http.post(
            "https://www.123pan.cn/b/api/file/s3_complete_multipart_upload",
            json=uploaded_comp_data,
            timeout=10,
        )

        if fsize > 64 * 1024 * 1024:
            time.sleep(3)

        close_up_session_data = {"fileId": up_file_id}
        close_res = self._session.http.post(
            "https://www.123pan.cn/b/api/file/upload_complete",
            json=close_up_session_data,
            timeout=10,
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

    def upload_file_stream(
        self, file_path, parent_file_id, dup_choice=1, signals=None, task=None
    ):
        """上传文件，支持进度回调、取消/暂停控制。

        Args:
            file_path: 本地文件路径
            parent_file_id: 目标目录ID
            dup_choice: 重复文件处理策略
            signals: 可选信号对象（需有 progress 信号）
            task: 可选的任务控制对象（需有 is_cancelled 属性）

        Returns:
            int: 上传后的文件ID（成功）
            str: "已取消" 如果被取消
            str: "复用上传成功" 如果服务端已存在
        """
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_path_obj = Path(file_path)
        file_name = file_path_obj.name
        if not file_path_obj.exists():
            raise FileNotFoundError("文件不存在")
        if file_path_obj.is_dir():
            raise IsADirectoryError("不支持文件夹上传")
        fsize = file_path_obj.stat().st_size

        readable_hash = self.compute_file_md5(file_path)
        if task and task.is_cancelled:
            return "已取消"

        list_up_request = {
            "driveId": 0,
            "etag": readable_hash,
            "fileName": file_name,
            "parentFileId": parent_file_id,
            "size": fsize,
            "type": 0,
            "duplicate": 0,
        }
        url = "https://www.123pan.cn/b/api/file/upload_request"
        res = self._session.http.post(url, data=list_up_request, timeout=30)
        res_json = res.json()
        code = res_json.get("code", -1)
        if code == 5060:
            list_up_request["duplicate"] = dup_choice
            res = self._session.http.post(url, json=list_up_request, timeout=30)
            res_json = res.json()
            code = res_json.get("code", -1)
        if code != 0:
            raise RuntimeError(
                "上传请求失败: " + json.dumps(res_json, ensure_ascii=False)
            )

        data = res_json["data"]
        if data.get("Reuse"):
            return "复用上传成功"

        bucket = data["Bucket"]
        storage_node = data["StorageNode"]
        upload_key = data["Key"]
        upload_id = data["UploadId"]
        up_file_id = data["FileId"]

        block_size = 5242880
        total_sent = 0
        part_number = 1
        with open(file_path, "rb") as f:
            while True:
                block = f.read(block_size)
                if not block:
                    break

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
                if get_link_res_json.get("code", -1) != 0:
                    raise RuntimeError(
                        "获取上传链接失败: " + json.dumps(get_link_res_json, ensure_ascii=False)
                    )
                upload_url = get_link_res_json["data"]["presignedUrls"][str(part_number)]
                self._session.transfer.put(upload_url, data=block, timeout=60)
                total_sent += len(block)
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

        close_res = self._session.http.post(
            "https://www.123pan.cn/b/api/file/upload_complete",
            json={"fileId": up_file_id},
            timeout=30,
        )
        cr = close_res.json()
        if cr.get("code", -1) != 0:
            raise RuntimeError("上传完成确认失败: " + json.dumps(cr, ensure_ascii=False))
        return up_file_id
