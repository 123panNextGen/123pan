import hashlib
import io
import json
import math
import os
import queue
import random
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .database import Database, UPLOAD_PART_SIZE, _safe_int, get_upload_part_size
from .concurrency import (
    RATE_LIMIT_CODES, MAX_RATE_LIMITS, RATE_LIMIT_BACKOFF,
    MAX_PART_RETRIES, PROGRESS_INTERVAL, slow_start_scheduler,
)
from .const import all_device_type, all_os_versions
from .log import get_logger

logger = get_logger(__name__)

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
BACKOFF_MULTIPLIER = 2
MAX_CREATE_DIR_RETRIES = 10


class _ProgressIO:
    """将 bytes 包装为 file-like 对象，按阈值触发进度回调。"""
    _REPORT_SIZE = 256 * 1024  # 累积 256KB 才汇报一次

    def __init__(self, data, callback):
        self._buf = io.BytesIO(data)
        self._cb = callback
        self._pending = 0
        self.reported = 0

    def read(self, size=-1):
        chunk = self._buf.read(size)
        if chunk:
            self._pending += len(chunk)
            if self._pending >= self._REPORT_SIZE:
                self._cb(self._pending)
                self.reported += self._pending
                self._pending = 0
        elif self._pending > 0:
            self._cb(self._pending)
            self.reported += self._pending
            self._pending = 0
        return chunk

    def __len__(self):
        return len(self._buf.getbuffer())


class RateLimitError(RuntimeError):
    """API 返回 HTTP 429 限流。"""


def _parse_json_response(response):
    """统一解析 JSON 响应，避免裸 .json() 崩溃。"""
    try:
        return response.json()
    except (ValueError, KeyError) as exc:
        raise RuntimeError(
            f"JSON 解析失败 (HTTP {response.status_code}): {response.text[:200]}"
        ) from exc


def _calculate_file_md5(
    file_path, fsize, task=None, signals=None, speed_tracker=None,
    emit_progress=True,
):
    md5 = hashlib.md5()
    bytes_read = 0
    last_pct = -1
    with open(file_path, "rb") as f:
        while True:
            data = f.read(1024 * 1024)
            if not data:
                break
            md5.update(data)
            bytes_read += len(data)
            if task and getattr(task, "is_cancelled", False):
                return "已取消", ""
            if task and getattr(task, "pause_requested", False):
                return "已暂停", ""
            if emit_progress and fsize > 0:
                pct = int(bytes_read * 100 / fsize)
                if pct != last_pct:
                    last_pct = pct
                    if signals:
                        signals.progress.emit(pct)
                    if speed_tracker:
                        speed_tracker.record(bytes_read)
    return None, md5.hexdigest()


def _reset_transient_failure_count(counter):
    counter[0] = 0


class Pan123:
    """123云盘API客户端类"""

    def __init__(
        self,
        readfile=True,
        user_name="",
        password="",
        authorization="",
        input_pwd=False,
    ):

        # 设备信息（优先从配置读取，否则随机生成）
        self.devicetype = random.choice(all_device_type)
        self.osversion = random.choice(all_os_versions)
        self.loginuuid = uuid.uuid4().hex

        self.recycle_list = None
        self.list = []
        self.total = 0
        self.parent_file_name_list = []
        self.all_file = False
        self.file_page = 0
        # 创建带重试的 session，仅在网络错误时重试
        db = Database.instance()
        retry = Retry(
            total=_safe_int(db.get_config("retryMaxAttempts", 3), default=3, min_val=1, max_val=10),
            backoff_factor=db.get_config("retryBackoffFactor", 0.5),
            allowed_methods=["GET", "POST", "PUT", "HEAD"],
            raise_on_status=False,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._session_lock = threading.Lock()
        if readfile:
            self.read_ini(user_name, password, input_pwd, authorization)
        else:
            if user_name == "" or password == "":
                raise Exception("用户名或密码为空")
            self.user_name = user_name
            self.password = password
            self.authorization = authorization
        self.header_logined = {
            "user-agent": "123pan/v2.4.0(" + self.osversion + ";Xiaomi)",
            "authorization": self.authorization,
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "osversion": self.osversion,
            "loginuuid": self.loginuuid,
            "platform": "android",
            "devicetype": self.devicetype,
            "devicename": "Xiaomi",
            "app-version": "61",
            "x-app-version": "2.4.0",
        }
        self.parent_file_id = 0  # 路径，文件夹的id,0为根目录
        self.parent_file_list = [0]
        self._login_lock = threading.Lock()

    def login(self):
        with self._login_lock:
            return self._login_without_lock()

    def _login_without_lock(self):
        """登录123云盘账户并获取授权令牌"""
        data = {"type": 1, "passport": self.user_name, "password": self.password}
        with self._session_lock:
            login_res = self.session.post(
                "https://www.123pan.com/b/api/user/sign_in",
                headers=self.header_logined,
                data=json.dumps(data),
                timeout=(3, 5),
            )

        res_sign = _parse_json_response(login_res)
        res_code_login = res_sign.get("code", -1)
        if res_code_login != 200:
            logger.error("code = 1 Error:" + str(res_code_login))
            logger.error(res_sign.get("message", ""))
            return res_code_login

        token = res_sign.get("data", {}).get("token", "")
        if not token:
            logger.error("登录响应缺少 token")
            return -1
        self.authorization = "Bearer " + token
        self.header_logined["authorization"] = self.authorization
        self.save_file()
        return res_code_login

    def _prepare_request_kwargs(self, kwargs):
        request_kwargs = dict(kwargs)
        headers = request_kwargs.get("headers")
        if headers is None:
            request_kwargs["headers"] = self.header_logined
            return request_kwargs

        merged_headers = dict(headers)
        merged_headers["authorization"] = self.header_logined["authorization"]
        request_kwargs["headers"] = merged_headers
        return request_kwargs

    def _refresh_token_for_request(self, request_authorization):
        # 密码为空时无法通过重新登录刷新 token
        if not self.password:
            raise RuntimeError("token 过期且无保存密码，无法自动刷新")
        with self._login_lock:
            current_authorization = self.header_logined["authorization"]
            if request_authorization != current_authorization:
                return
            login_code = self._login_without_lock()
        if login_code not in (0, 200):
            raise RuntimeError(f"token 刷新失败: {login_code}")

    def _api_request(self, method, url, max_token_refreshes=1, **kwargs):
        token_refreshes = 0
        while True:
            request_kwargs = self._prepare_request_kwargs(kwargs)
            request_headers = request_kwargs.get("headers", {})
            request_authorization = request_headers.get("authorization")
            with self._session_lock:
                response = method(url, **request_kwargs)
            # 统一检测 429
            if response.status_code == 429:
                raise RateLimitError(f"API 返回 429 限流: {url}")
            try:
                response_json = response.json()
            except ValueError:
                return response
            if response_json.get("code") != 2 or token_refreshes >= max_token_refreshes:
                return response
            self._refresh_token_for_request(request_authorization)
            token_refreshes += 1

    def save_file(self):
        """将账户信息保存到配置文件"""
        try:
            db = Database.instance()
            remember_password = bool(db.get_config("rememberPassword", False))
            stay_logged_in = bool(db.get_config("stayLoggedIn", True))
            db.set_many_config({
                "userName": self.user_name,
                "passWord": self.password if remember_password else "",
                "authorization": self.authorization if stay_logged_in else "",
                "deviceType": self.devicetype,
                "osVersion": self.osversion,
            })
            logger.info("账号已保存")
        except Exception as e:
            logger.error("保存账号失败: %s", e)

    def get_dir_by_id(self, file_id, save=True, all=False, limit=100, search_data=""):
        """按文件夹ID获取文件列表（支持分页）"""
        get_pages = 3
        page = 1 if all or not save else self.file_page * get_pages + 1
        length_now = 0 if all or not save else len(self.list)
        lists = []
        total = -1
        times = 0
        while (length_now < total or total == -1) and (times < get_pages or all):
            base_url = "https://www.123pan.com/b/api/file/list/new"
            params = {
                "driveId": 0,
                "limit": limit,
                "next": 0,
                "orderBy": "file_id",
                "orderDirection": "desc",
                "parentFileId": str(file_id),
                "trashed": False,
                "SearchData": search_data,
                "Page": str(page),
                "OnlyLookAbnormalFile": 0,
            }
            try:
                response = self._api_request(
                    self.session.get,
                    base_url, headers=self.header_logined, params=params, timeout=30
                )
            except RateLimitError:
                logger.error("获取文件列表触发 429 限流")
                return -1, []
            except requests.exceptions.Timeout:
                logger.error(f"请求超时: {base_url}")
                return -1, []
            except requests.exceptions.ConnectionError as e:
                logger.error(f"连接失败: {e}")
                return -1, []
            except requests.exceptions.RequestException as e:
                logger.error(f"请求异常: {e}")
                return -1, []
            text = _parse_json_response(response)
            res_code_getdir = text.get("code", -1)
            if res_code_getdir != 0:
                logger.error("code = 2 Error:" + str(res_code_getdir))
                logger.error(text.get("message", ""))
                return res_code_getdir, []
            data = text.get("data") or {}
            lists_page = data.get("InfoList") or []
            lists += lists_page
            total = data.get("Total", 0)
            length_now += len(lists_page)
            page += 1
            times += 1
            if times % 5 == 0:
                logger.warning(
                    "警告：文件夹内文件过多：" + str(length_now) + "/" + str(total)
                )
                logger.info("为防止对服务器造成影响，暂停3秒")
                time.sleep(3)

        if not save:
            return res_code_getdir, lists
        if length_now < total:
            logger.warning("文件夹内文件过多：" + str(length_now) + "/" + str(total))
            self.all_file = False
        else:
            self.all_file = True
        self.total = total
        self.file_page += 1
        if save:
            self.list.extend(lists)

        return res_code_getdir, lists

    def link_by_fileDetail(self, file_detail, showlink=True):
        """按文件详情获取下载链接"""
        type_detail = file_detail.get("Type", 0)

        if type_detail == 1:
            down_request_url = "https://www.123pan.com/a/api/file/batch_download_info"
            down_request_data = {"fileIdList": [{"fileId": int(file_detail.get("FileId", 0))}]}

        else:
            down_request_url = "https://www.123pan.com/a/api/file/download_info"
            down_request_data = {
                "driveId": 0,
                "etag": file_detail.get("Etag", ""),
                "fileId": file_detail.get("FileId", 0),
                "s3keyFlag": file_detail.get("S3KeyFlag", False),
                "type": file_detail.get("Type", 0),
                "fileName": file_detail.get("FileName", ""),
                "size": file_detail.get("Size", 0),
            }

        link_res = self._api_request(
            self.session.post,
            down_request_url,
            headers=self.header_logined,
            data=json.dumps(down_request_data),
            timeout=10,
        )
        link_res_json = _parse_json_response(link_res)
        res_code_download = link_res_json.get("code", -1)
        if res_code_download != 0:
            logger.error("获取下载链接失败，返回码: " + str(res_code_download))
            logger.error(link_res_json.get("message", ""))
            return res_code_download
        down_load_url = link_res_json.get("data", {}).get("DownloadUrl", "")
        if not down_load_url:
            logger.error("响应中缺少 DownloadUrl")
            return -1
        with self._session_lock:
            next_to_get = self.session.get(
                down_load_url, timeout=10, allow_redirects=False
            ).text
        url_pattern = re.compile(r"""href=["'](https?://[^"']+)["']""")
        matches = url_pattern.findall(next_to_get)
        if not matches:
            logger.error("未找到重定向链接，响应内容: %s", next_to_get[:200])
            return -1
        redirect_url = matches[0]
        if showlink:
            parsed = urlparse(redirect_url)
            logger.info(f"获取下载链接成功: {parsed.hostname}")

        return redirect_url

    def recycle(self):
        """获取回收站列表"""
        recycle_id = 0
        url = (
            "https://www.123pan.com/a/api/file/list/new?driveId=0&limit=100&next=0"
            "&orderBy=fileId&orderDirection=desc&parentFileId="
            + str(recycle_id)
            + "&trashed=true&Page=1"
        )
        recycle_res = self._api_request(
            self.session.get,
            url,
            headers=self.header_logined,
            timeout=10,
        )
        json_recycle = _parse_json_response(recycle_res)
        recycle_list = json_recycle.get("data", {}).get("InfoList", [])
        self.recycle_list = recycle_list

    def delete_file(self, file, by_num=True, operation=True):
        """删除或恢复文件"""
        if by_num:
            if not str(file).isdigit():
                raise ValueError("文件索引必须是数字")
            if 0 <= file < len(self.list):
                file_detail = self.list[file]
            else:
                raise IndexError("文件索引超出范围")
        else:
            file_detail = file
        data_delete = {
            "driveId": 0,
            "fileTrashInfoList": file_detail,
            "operation": operation,
        }
        delete_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/a/api/file/trash",
            data=json.dumps(data_delete),
            headers=self.header_logined,
            timeout=10,
        )
        dele_json = _parse_json_response(delete_res)
        if dele_json.get("code", -1) != 0:
            raise RuntimeError(
                "删除文件失败: " + json.dumps(dele_json, ensure_ascii=False)
            )
        logger.debug(f"删除文件响应: {dele_json}")
        message = dele_json.get("message", "")
        logger.info(f"删除文件消息: {message}")

    def rename_file(self, file_id, new_name):
        """重命名文件或文件夹"""
        data = {"driveId": 0, "fileId": file_id, "fileName": new_name}
        rename_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/a/api/file/rename",
            data=json.dumps(data),
            headers=self.header_logined,
            timeout=10,
        )
        rename_json = _parse_json_response(rename_res)
        code = rename_json.get("code", -1)
        logger.debug(f"重命名文件响应: {rename_json}")
        if code != 0:
            message = rename_json.get("message", "")
            logger.error(f"重命名失败: {message}")
            return False
        logger.info(f"重命名成功: {new_name}")
        return True

    def move_file(self, file_id_list, target_parent_id):
        """移动文件或文件夹到目标目录"""
        data = {
            "fileIdList": [{"FileId": fid} for fid in file_id_list],
            "parentFileId": target_parent_id,
        }
        move_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/b/api/file/mod_pid",
            data=json.dumps(data),
            headers=self.header_logined,
            timeout=10,
        )
        move_json = _parse_json_response(move_res)
        code = move_json.get("code", -1)
        logger.debug(f"移动文件响应: {move_json}")
        if code != 0:
            message = move_json.get("message", "")
            logger.error(f"移动文件失败: {message}")
            return False
        logger.info(f"移动文件成功: {len(file_id_list)} 个文件")
        return True

    def user_info(self):
        """获取用户信息（已用空间、总容量、VIP 等）"""
        res = self._api_request(
            self.session.get,
            "https://api.123pan.cn/b/api/user/info",
            headers=self.header_logined,
            timeout=10,
        )
        res_json = _parse_json_response(res)
        code = res_json.get("code", -1)
        if code != 0:
            message = res_json.get("message", "")
            logger.error(f"获取用户信息失败: {message}")
            return None
        return res_json.get("data")

    def qr_generate(self):
        """获取二维码登录会话（uniID + url）。"""
        headers = {
            "loginuuid": self.loginuuid,
            "app-version": "3",
            "platform": "web",
            "content-type": "application/json;charset=UTF-8",
        }
        with self._session_lock:
            res = self.session.get(
                "https://login.123pan.com/api/user/qr-code/generate",
                headers=headers,
                timeout=10,
            )
        res_json = _parse_json_response(res)
        code = res_json.get("code", -1)
        if code != 0:
            raise RuntimeError(
                f"获取二维码失败: code={code}, "
                f"message={res_json.get('message', '')}"
            )
        data = res_json.get("data", {})
        return {"uniID": data.get("uniID", ""), "url": data.get("url", "")}

    def qr_poll(self, uni_id):
        """轮询二维码扫码状态。

        返回 dict:
        - loginStatus: 0=等待扫码, 1=已扫码待确认, 2=拒绝, 3=确认登录, 4=过期
        - scanPlatform: 4=微信, 7=123云盘App (仅 code=200 时从 login_type 取)
        - token: JWT token (仅 App 扫码确认时直接返回)
        """
        headers = {
            "loginuuid": self.loginuuid,
            "app-version": "3",
            "platform": "web",
            "content-type": "application/json;charset=UTF-8",
        }
        with self._session_lock:
            res = self.session.get(
                "https://login.123pan.com/api/user/qr-code/result",
                headers=headers,
                params={"uniID": uni_id},
                timeout=10,
            )
        res_json = _parse_json_response(res)
        code = res_json.get("code", -1)
        data = res_json.get("data", {})

        # code=200 表示用户确认登录（前端映射为 loginStatus=3）
        if code == 200:
            return {
                "loginStatus": 3,
                "scanPlatform": data.get("login_type", 0),
                "token": data.get("token", ""),
            }

        if code != 0:
            raise RuntimeError(
                f"轮询扫码状态失败: code={code}, "
                f"message={res_json.get('message', '')}"
            )
        return {
            "loginStatus": data.get("loginStatus", -1),
            "scanPlatform": data.get("scanPlatform", 0),
        }

    def qr_wx_code(self, uni_id):
        """微信扫码登录：用 uniID 换取 wxCode，再用 wxCode 换 token。"""
        headers = {
            "loginuuid": self.loginuuid,
            "app-version": "3",
            "platform": "web",
            "content-type": "application/json;charset=UTF-8",
        }
        with self._session_lock:
            res = self.session.post(
                "https://login.123pan.com/api/user/qr-code/wx_code",
                headers=headers,
                json={"uniID": uni_id},
                timeout=10,
            )
        res_json = _parse_json_response(res)
        code = res_json.get("code", -1)
        if code != 0:
            raise RuntimeError(
                f"获取 wxCode 失败: code={code}, "
                f"message={res_json.get('message', '')}"
            )
        data = res_json.get("data", {})
        return data.get("wxCode", "")

    def file_details(self, file_ids):
        """获取文件/文件夹详情"""
        data = {"file_ids": file_ids}
        res = self._api_request(
            self.session.post,
            "https://www.123pan.com/b/api/restful/goapi/v1/file/details",
            data=json.dumps(data),
            headers=self.header_logined,
            timeout=10,
        )
        res_json = _parse_json_response(res)
        code = res_json.get("code", -1)
        if code != 0:
            message = res_json.get("message", "")
            logger.error(f"获取文件详情失败: {message}")
            return None
        data = res_json.get("data")
        logger.debug(f"file_details 响应 paths: {data.get('paths') if data else None}")
        return data

    def share(self, file_id_list, share_pwd=""):
        """分享文件"""
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
        share_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/a/api/share/create",
            headers=self.header_logined,
            data=json.dumps(data),
            timeout=10,
        )
        share_res_json = _parse_json_response(share_res)
        if share_res_json.get("code", -1) != 0:
            raise RuntimeError(f"分享失败: {share_res_json.get('message', '')}")
        share_key = share_res_json.get("data", {}).get("ShareKey", "")
        if not share_key:
            raise RuntimeError("分享响应缺少 ShareKey")
        share_url = "https://www.123pan.com/s/" + share_key
        return share_url

    def read_ini(
        self,
        user_name,
        password,
        input_pwd,
        authorization="",
    ):
        """从配置文件读取账号信息"""
        try:
            db = Database.instance()
            deviceType = db.get_config("deviceType", "")
            osVersion = db.get_config("osVersion", "")
            loginuuid = db.get_config("loginuuid", "")
            if deviceType:
                self.devicetype = deviceType
            if osVersion:
                self.osversion = osVersion
            if loginuuid:
                self.loginuuid = loginuuid
            user_name = db.get_config("userName", user_name) or user_name
            password = db.get_config("passWord", password) or password
            authorization = db.get_config("authorization", authorization) or authorization
        except Exception as e:
            logger.error(f"获取配置失败: {e}")
            if user_name == "" or password == "":
                raise Exception("无法从配置获取账号信息")

        self.user_name = user_name
        self.password = password
        self.authorization = authorization

    def mkdir(self, dirname, remakedir=False):
        """创建文件夹"""
        if not remakedir:
            for i in self.list:
                if i["FileName"] == dirname:
                    logger.info("文件夹已存在")
                    return i["FileId"]

        return self._create_directory(self.parent_file_id, dirname)

    def _create_directory(self, parent_id, dirname):
        """在指定父目录下创建文件夹。"""
        url = "https://www.123pan.com/a/api/file/upload_request"
        data_mk = {
            "driveId": 0,
            "etag": "",
            "fileName": dirname,
            "parentFileId": parent_id,
            "size": 0,
            "type": 1,
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }
        res_mk = self._api_request(
            self.session.post,
            url,
            headers=self.header_logined,
            data=json.dumps(data_mk),
            timeout=10,
        )
        try:
            res_json = res_mk.json()
        except json.decoder.JSONDecodeError:
            logger.error("创建失败")
            logger.error(res_mk.text)
            raise RuntimeError(f"创建目录 '{dirname}' 响应解析失败")
        code_mkdir = res_json.get("code", -1)

        if code_mkdir == 0:
            logger.info(f"创建成功: {res_json.get('data', {}).get('FileId')}")
            return res_json.get("data", {}).get("Info", {}).get("FileId")
        logger.error(f"创建失败: {res_json}")
        raise RuntimeError(
            f"创建目录 '{dirname}' 失败: code={code_mkdir}, "
            f"message={res_json.get('message', '')}"
        )

    def _create_directory_with_backoff(self, parent_id, dirname):
        """创建目录，遇到 429 时进行指数退避重试。"""
        backoff = INITIAL_BACKOFF_SECONDS
        for attempt in range(MAX_CREATE_DIR_RETRIES + 1):
            try:
                return self._create_directory(parent_id, dirname)
            except RateLimitError as exc:
                if attempt >= MAX_CREATE_DIR_RETRIES:
                    raise RuntimeError(
                        f"创建目录 '{dirname}' 触发 429 限流，"
                        f"已重试 {MAX_CREATE_DIR_RETRIES} 次"
                    ) from exc
                logger.warning(
                    "目录创建 429，退避 %.1fs（第 %d 次）",
                    backoff,
                    attempt + 1,
                )
                time.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS)

    def _get_dir_items_by_id(self, parent_id):
        """获取指定目录下的完整文件列表，不污染当前分页状态。"""
        code, items = self.get_dir_by_id(parent_id, save=False, all=True, limit=100)
        if code != 0:
            raise RuntimeError(f"获取目录失败，返回码: {code}")
        return items

    def _get_child_directory_map(self, parent_id):
        """返回指定目录下子目录名到目录 ID 的映射。"""
        child_dirs = {}
        for item in self._get_dir_items_by_id(parent_id):
            if int(item.get("Type", 0) or 0) != 1:
                continue
            child_dirs[item.get("FileName", "")] = int(item.get("FileId", 0) or 0)
        return child_dirs

    @staticmethod
    def _choose_available_directory_name(existing_names, dirname):
        """根据已有目录名生成可用名称。"""
        if dirname not in existing_names:
            return dirname

        index = 1
        while True:
            candidate = f"{dirname}({index})"
            if candidate not in existing_names:
                return candidate
            index += 1

    def ensure_directory(self, parent_id, dirname):
        """确保指定父目录下存在目标子目录。"""
        child_dirs = self._get_child_directory_map(parent_id)
        if dirname in child_dirs:
            return child_dirs[dirname]

        created_id = self._create_directory_with_backoff(parent_id, dirname)
        if not created_id:
            raise RuntimeError(f"创建目录失败: {dirname}")
        return created_id

    def prepare_folder_upload(self, local_dir, target_parent_id):
        """创建远端目录结构，并返回文件上传计划。"""
        local_dir_path = Path(local_dir)
        if not local_dir_path.exists():
            raise FileNotFoundError(f"文件夹不存在: {local_dir_path}")
        if not local_dir_path.is_dir():
            raise NotADirectoryError(f"不是文件夹: {local_dir_path}")

        top_level_dirs = self._get_child_directory_map(target_parent_id)
        root_name = self._choose_available_directory_name(
            set(top_level_dirs), local_dir_path.name
        )
        root_dir_id = self._create_directory_with_backoff(target_parent_id, root_name)
        if not root_dir_id:
            raise RuntimeError(f"创建顶层目录失败: {root_name}")

        dir_id_map = {Path("."): root_dir_id}
        file_targets = []
        created_dir_count = 1

        try:
            for current_root, dir_names, file_names in os.walk(local_dir_path):
                dir_names.sort()
                file_names.sort()
                current_path = Path(current_root)
                relative_root = current_path.relative_to(local_dir_path)
                remote_parent_id = dir_id_map[relative_root or Path(".")]

                for dir_name in dir_names:
                    child_relative = relative_root / dir_name
                    child_dir_id = self._create_directory_with_backoff(
                        remote_parent_id,
                        dir_name,
                    )
                    if not child_dir_id:
                        raise RuntimeError(f"创建目录失败: {child_relative}")
                    dir_id_map[child_relative] = child_dir_id
                    created_dir_count += 1

                for file_name in file_names:
                    file_targets.append({
                        "file_name": file_name,
                        "local_path": str(current_path / file_name),
                        "target_dir_id": remote_parent_id,
                        "file_size": (current_path / file_name).stat().st_size,
                    })
        except Exception:
            try:
                self.delete_file(
                    {"FileId": root_dir_id, "Type": 1, "FileName": root_name},
                    by_num=False,
                )
            except Exception as cleanup_exc:
                logger.warning("回滚上传目录失败: %s", cleanup_exc)
            raise

        return {
            "root_dir_id": root_dir_id,
            "root_dir_name": root_name,
            "created_dir_count": created_dir_count,
            "file_targets": file_targets,
        }

    def upload_file_stream(
        self, file_path, dup_choice=1, task_id=None, signals=None, task=None,
        speed_tracker=None, resume_info=None, parent_id=0,
    ):
        """上传文件（分块），支持断点续传、progress 回调与取消/暂停控制。"""
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_path_obj = Path(file_path)
        file_name = file_path_obj.name
        if not file_path_obj.exists():
            raise FileNotFoundError("文件不存在")
        if file_path_obj.is_dir():
            raise IsADirectoryError("不支持文件夹上传")
        fsize = file_path_obj.stat().st_size
        headers = self.header_logined.copy()
        readable_hash = None

        if resume_info and resume_info.get("upload_id"):
            stored_hash = resume_info.get("etag", "")
            if not stored_hash:
                logger.warning("断点续传缺少 etag，改为重新上传")
                resume_info = None
            else:
                if signals and hasattr(signals, "status"):
                    signals.status.emit("校验中")
                stop_state, readable_hash = _calculate_file_md5(
                    file_path,
                    fsize,
                    task=task,
                    emit_progress=False,
                )
                if stop_state:
                    return stop_state
                if readable_hash != stored_hash:
                    logger.warning("检测到本地文件已变更，放弃旧续传会话并重新上传")
                    if signals:
                        signals.progress.emit(0)
                    if speed_tracker:
                        speed_tracker.reset()
                    resume_info = None

        if resume_info and resume_info.get("upload_id"):
            # ---- 断点续传：复用已有 S3 session ----
            bucket = resume_info["bucket"]
            storage_node = resume_info["storage_node"]
            upload_key = resume_info["upload_key"]
            upload_id = resume_info["upload_id"]
            up_file_id = resume_info["up_file_id"]
            block_size = resume_info.get("block_size", UPLOAD_PART_SIZE)
            total_parts = resume_info.get("total_parts") or (
                math.ceil(fsize / block_size) if fsize > 0 else 1
            )
            done_parts = resume_info.get("done_parts", set())

            # C4: 用服务端实际存在的 parts 与本地记录做交集
            try:
                list_data = {
                    "bucket": bucket,
                    "key": upload_key,
                    "uploadId": upload_id,
                    "storageNode": storage_node,
                }
                list_res = self._api_request(
                    self.session.post,
                    "https://www.123pan.com/b/api/file/s3_list_upload_parts",
                    headers=headers,
                    data=json.dumps(list_data),
                    timeout=30,
                )
                list_json = _parse_json_response(list_res)
                if list_json.get("code", -1) == 0:
                    server_parts_data = list_json.get("data", {}).get("parts") or []
                    server_part_numbers = {int(p.get("PartNumber", 0)) for p in server_parts_data}
                    done_parts = done_parts & server_part_numbers
                else:
                    logger.warning(
                        "验证服务端已上传分块返回异常，将重新上传所有分块: %s",
                        json.dumps(list_json, ensure_ascii=False),
                    )
                    done_parts = set()
            except Exception as exc:
                logger.warning("验证服务端已上传分块失败，将重新上传所有分块: %s", exc)
                done_parts = set()

            logger.info(
                "断点续传: %s/%s 块已完成", len(done_parts), total_parts
            )
            if signals and hasattr(signals, "status"):
                signals.status.emit("上传中")
        else:
            # ---- 全新上传：先校验文件 MD5 ----
            if readable_hash is None:
                if signals and hasattr(signals, "status"):
                    signals.status.emit("校验中")
                stop_state, readable_hash = _calculate_file_md5(
                    file_path,
                    fsize,
                    task=task,
                    signals=signals,
                    speed_tracker=speed_tracker,
                )
                if stop_state:
                    return stop_state

            list_up_request = {
                "driveId": 0,
                "etag": readable_hash,
                "fileName": file_name,
                "parentFileId": parent_id,
                "size": fsize,
                "type": 0,
                "duplicate": 0,
            }
            url = "https://www.123pan.com/b/api/file/upload_request"
            res = self._api_request(
                self.session.post,
                url,
                headers=headers,
                data=json.dumps(list_up_request),
                timeout=30,
            )
            res_json = _parse_json_response(res)
            code = res_json.get("code", -1)
            if code == 5060:
                list_up_request["duplicate"] = dup_choice
                res = self._api_request(
                    self.session.post,
                    url,
                    headers=headers,
                    data=json.dumps(list_up_request),
                    timeout=30,
                )
                res_json = _parse_json_response(res)
                code = res_json.get("code", -1)
            if code != 0:
                raise RuntimeError(
                    "上传请求失败: " + json.dumps(res_json, ensure_ascii=False)
                )
            data = res_json.get("data") or {}
            if data.get("Reuse"):
                return "复用上传成功"
            bucket = data.get("Bucket", "")
            storage_node = data.get("StorageNode", "")
            upload_key = data.get("Key", "")
            upload_id = data.get("UploadId", "")
            up_file_id = data.get("FileId", 0)
            block_size = get_upload_part_size()
            total_parts = math.ceil(fsize / block_size) if fsize > 0 else 1
            done_parts = set()

            # 回传 S3 session 信息给 UI 持久化
            if signals and hasattr(signals, "session_info"):
                signals.session_info.emit({
                    "bucket": bucket, "storage_node": storage_node,
                    "upload_key": upload_key, "upload_id": upload_id,
                    "up_file_id": up_file_id, "total_parts": total_parts,
                    "block_size": block_size, "etag": readable_hash,
                })

            # 校验完成，切换到上传状态并重置进度
            if signals and hasattr(signals, "status"):
                signals.status.emit("上传中")
            if signals:
                signals.progress.emit(0)
            if speed_tracker:
                speed_tracker.reset()

        # 初始化 multipart upload session（123pan 要求在获取 presigned URL 前调用）
        init_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        init_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/b/api/file/s3_list_upload_parts",
            headers=headers,
            data=json.dumps(init_data),
            timeout=30,
        )
        init_json = _parse_json_response(init_res)
        if init_json.get("code", -1) != 0:
            raise RuntimeError(
                "初始化上传会话失败: " + json.dumps(init_json, ensure_ascii=False)
            )

        # 构建分块任务队列（跳过已完成的块）
        part_queue = queue.Queue()
        done_bytes = 0
        for part_num in range(1, total_parts + 1):
            offset = (part_num - 1) * block_size
            size = min(block_size, fsize - offset)
            if part_num in done_parts:
                done_bytes += size
            else:
                part_queue.put({"part_number": part_num, "offset": offset, "size": size})

        max_workers = min(
            max(
                1,
                _safe_int(
                    Database.instance().get_config("maxUploadThreads", 16),
                    default=16, min_val=1, max_val=16,
                ),
            ),
            16,
        )
        if total_parts == 1:
            max_workers = 1

        logger.debug("上传任务并发上限: %s, 分块数: %s, 已完成: %s", max_workers, total_parts, len(done_parts))
        active_workers = [0]
        allowed_workers = [1]
        failed = [False]
        uploaded = [done_bytes]
        transient_failure_count = [0]
        progress_lock = threading.Lock()
        last_progress_time = [0.0]
        probe_phase = [True]
        probe_failed = [False]
        probe_success_count = [0]
        worker_feedback = threading.Event()

        # 续传时立即发送已有进度
        if done_bytes > 0 and signals and fsize:
            signals.progress.emit(int(done_bytes * 100 / fsize))

        # 记录初始点，使第一块完成后即可计算速度
        if speed_tracker:
            speed_tracker.record(done_bytes)

        def _is_stopped():
            if task and getattr(task, "is_cancelled", False):
                return True
            if task and getattr(task, "pause_requested", False):
                return True
            return False

        def _upload_worker():
            with progress_lock:
                active_workers[0] += 1
                if signals and hasattr(signals, "conn_info"):
                    signals.conn_info.emit(active_workers[0], allowed_workers[0])
            logger.debug("上传 worker 启动: active=%s", active_workers[0])

            try:
                while not failed[0]:
                    if _is_stopped():
                        logger.debug("上传 worker 因任务停止退出")
                        return
                    with progress_lock:
                        if active_workers[0] > allowed_workers[0] and active_workers[0] > 1:
                            logger.debug(
                                "上传 worker 为满足并发上限退出: active=%s, allowed=%s",
                                active_workers[0],
                                allowed_workers[0],
                            )
                            return
                    try:
                        part = part_queue.get_nowait()
                    except queue.Empty:
                        logger.debug("上传 worker 发现队列为空，退出")
                        return

                    pn = part["part_number"]
                    offset = part["offset"]
                    size = part["size"]

                    logger.debug(
                        "上传 worker 获取分块 %s，剩余队列=%s",
                        pn,
                        part_queue.qsize(),
                    )

                    retry = 0
                    while retry < MAX_PART_RETRIES:
                        progress_io = None
                        if _is_stopped():
                            logger.debug("分块 %s 上传中停止", pn)
                            return
                        try:
                            # 逐块获取 presigned URL（避免批量获取导致 URL 过期）
                            url_data = {
                                "bucket": bucket,
                                "key": upload_key,
                                "partNumberEnd": pn + 1,
                                "partNumberStart": pn,
                                "uploadId": upload_id,
                                "StorageNode": storage_node,
                            }
                            url_res = self._api_request(
                                self.session.post,
                                "https://www.123pan.com/b/api/file/s3_repare_upload_parts_batch",
                                headers=headers,
                                data=json.dumps(url_data),
                                timeout=30,
                            )
                            url_json = _parse_json_response(url_res)
                            if url_json.get("code", -1) != 0:
                                raise requests.RequestException(
                                    "获取上传链接失败: "
                                    + json.dumps(url_json, ensure_ascii=False)
                                )
                            presigned_urls = url_json.get("data", {}).get("presignedUrls", {})
                            url = presigned_urls.get(str(pn), "")
                            if not url:
                                raise requests.RequestException(f"分块 {pn} 无 presigned URL")

                            with open(file_path, "rb") as f:
                                f.seek(offset)
                                block = f.read(size)

                            def _on_chunk(n):
                                with progress_lock:
                                    uploaded[0] += n
                                    if speed_tracker:
                                        speed_tracker.record(uploaded[0])
                                    if signals and fsize:
                                        now = time.time()
                                        if now - last_progress_time[0] > PROGRESS_INTERVAL:
                                            signals.progress.emit(
                                                int(uploaded[0] * 100 / fsize)
                                            )
                                            last_progress_time[0] = now

                            progress_io = _ProgressIO(block, _on_chunk)
                            resp = requests.put(url, data=progress_io, timeout=60)
                            if resp.status_code in RATE_LIMIT_CODES:
                                with progress_lock:
                                    uploaded[0] -= progress_io.reported
                                    transient_failure_count[0] += 1
                                    if transient_failure_count[0] > MAX_RATE_LIMITS:
                                        failed[0] = True
                                        logger.error("限流次数过多，上传终止")
                                        return
                                    new_limit = max(1, active_workers[0] - 1)
                                    if new_limit < allowed_workers[0]:
                                        allowed_workers[0] = new_limit
                                    if probe_phase[0]:
                                        probe_failed[0] = True
                                        probe_phase[0] = False
                                    if signals and hasattr(signals, "conn_info"):
                                        signals.conn_info.emit(
                                            active_workers[0], allowed_workers[0]
                                        )
                                part_queue.put(part)
                                worker_feedback.set()
                                logger.debug(
                                    "分块 %s 命中 %s，回队，allowed=%s",
                                    pn,
                                    resp.status_code,
                                    allowed_workers[0],
                                )
                                time.sleep(RATE_LIMIT_BACKOFF)
                                break
                            resp.raise_for_status()
                            part_etag = resp.headers.get("ETag", "")
                            if signals and hasattr(signals, "part_done"):
                                signals.part_done.emit(pn, part_etag)
                            with progress_lock:
                                probe_success_count[0] += 1
                                _reset_transient_failure_count(transient_failure_count)
                            worker_feedback.set()
                            logger.debug("分块 %s 上传成功", pn)
                            break
                        except Exception as exc:
                            if progress_io is not None and progress_io.reported > 0:
                                with progress_lock:
                                    uploaded[0] -= progress_io.reported
                            is_conn_err = isinstance(exc, requests.ConnectionError)
                            is_rate_limit_err = isinstance(exc, RateLimitError)
                            if is_rate_limit_err:
                                with progress_lock:
                                    transient_failure_count[0] += 1
                                    if transient_failure_count[0] > MAX_RATE_LIMITS:
                                        failed[0] = True
                                        logger.error("限流次数过多，上传终止")
                                        return
                                    new_limit = max(1, active_workers[0] - 1)
                                    if new_limit < allowed_workers[0]:
                                        allowed_workers[0] = new_limit
                                    if probe_phase[0]:
                                        probe_failed[0] = True
                                        probe_phase[0] = False
                                    if signals and hasattr(signals, "conn_info"):
                                        signals.conn_info.emit(
                                            active_workers[0], allowed_workers[0]
                                        )
                                part_queue.put(part)
                                worker_feedback.set()
                                logger.warning(
                                    "分块 %s 获取上传链接触发限流，回队重试: %s",
                                    pn, exc,
                                )
                                time.sleep(RATE_LIMIT_BACKOFF)
                                break
                            if is_conn_err:
                                with progress_lock:
                                    transient_failure_count[0] += 1
                                    if transient_failure_count[0] > MAX_RATE_LIMITS:
                                        failed[0] = True
                                        logger.error("连接错误次数过多，上传终止")
                                        return
                                    new_limit = max(1, active_workers[0] - 1)
                                    if new_limit < allowed_workers[0]:
                                        allowed_workers[0] = new_limit
                                        logger.info(
                                            "连接被重置，降低并发至 %s",
                                            allowed_workers[0],
                                        )
                                    if probe_phase[0]:
                                        probe_failed[0] = True
                                        probe_phase[0] = False
                                    if signals and hasattr(signals, "conn_info"):
                                        signals.conn_info.emit(
                                            active_workers[0], allowed_workers[0]
                                        )
                                worker_feedback.set()
                            retry += 1
                            if retry >= MAX_PART_RETRIES:
                                logger.error(
                                    "分块 %s 上传失败（已重试 %s 次）: %s",
                                    pn, retry, exc,
                                )
                                with progress_lock:
                                    if probe_phase[0]:
                                        probe_failed[0] = True
                                        probe_phase[0] = False
                                failed[0] = True
                                worker_feedback.set()
                                return
                            logger.warning(
                                "分块 %s 第 %s 次重试: %s", pn, retry, exc
                            )
                            time.sleep(2 ** retry)
            finally:
                with progress_lock:
                    active_workers[0] -= 1
                    if signals and hasattr(signals, "conn_info"):
                        signals.conn_info.emit(
                            active_workers[0], allowed_workers[0]
                        )
                worker_feedback.set()
                logger.debug("上传 worker 退出: active=%s", active_workers[0])

        def _notify_conn(active, allowed):
            if signals and hasattr(signals, "conn_info"):
                signals.conn_info.emit(active, allowed)

        slow_start_scheduler(
            worker_fn=_upload_worker,
            max_workers=max_workers,
            part_queue=part_queue,
            progress_lock=progress_lock,
            active_workers=active_workers,
            allowed_workers=allowed_workers,
            failed=failed,
            probe_failed=probe_failed,
            probe_success_count=probe_success_count,
            probe_phase=probe_phase,
            worker_feedback=worker_feedback,
            is_stopped_fn=_is_stopped,
            notify_conn_fn=_notify_conn,
            thread_prefix="upload_worker",
        )

        logger.debug(
            "上传线程全部退出: uploaded=%s/%s, failed=%s",
            uploaded[0],
            fsize,
            failed[0],
        )

        if signals and fsize:
            signals.progress.emit(int(uploaded[0] * 100 / fsize))
        if signals and hasattr(signals, "conn_info"):
            signals.conn_info.emit(0, allowed_workers[0])

        if task and getattr(task, "is_cancelled", False):
            return "已取消"
        if task and getattr(task, "pause_requested", False):
            return "已暂停"
        if failed[0]:
            raise RuntimeError("分块上传失败")

        # ---- 合并分块 ----
        uploaded_comp_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        # C2: 检查 s3_list_upload_parts 和 s3_complete_multipart_upload 返回值
        list_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/b/api/file/s3_list_upload_parts",
            headers=headers,
            data=json.dumps(uploaded_comp_data),
            timeout=30,
        )
        list_json = _parse_json_response(list_res)
        if list_json.get("code", -1) != 0:
            raise RuntimeError(
                "列出上传分块失败: " + json.dumps(list_json, ensure_ascii=False)
            )

        complete_res = self._api_request(
            self.session.post,
            "https://www.123pan.com/b/api/file/s3_complete_multipart_upload",
            headers=headers,
            data=json.dumps(uploaded_comp_data),
            timeout=30,
        )
        complete_json = _parse_json_response(complete_res)
        if complete_json.get("code", -1) != 0:
            raise RuntimeError(
                "合并上传分块失败: " + json.dumps(complete_json, ensure_ascii=False)
            )

        # M19: 轮询 upload_complete 替代盲等 sleep(3)
        close_up_session_data = {"fileId": up_file_id}
        max_complete_retries = 5
        for attempt in range(max_complete_retries):
            if attempt > 0:
                time.sleep(min(2 ** attempt, 8))
            close_res = self._api_request(
                self.session.post,
                "https://www.123pan.com/b/api/file/upload_complete",
                headers=headers,
                data=json.dumps(close_up_session_data),
                timeout=30,
            )
            cr = _parse_json_response(close_res)
            if cr.get("code", -1) == 0:
                return up_file_id
            if attempt < max_complete_retries - 1:
                logger.warning("upload_complete 未就绪 (attempt %d): %s", attempt + 1, cr.get("message", ""))
                continue
            raise RuntimeError(
                "上传完成确认失败: " + json.dumps(cr, ensure_ascii=False)
            )
        return up_file_id


# ==================== 工具函数和任务管理模块 ====================


def format_file_size(size):
    """格式化文件大小"""
    if size > 1073741824:
        return f"{round(size / 1073741824, 2)} GB"
    elif size > 1048576:
        return f"{round(size / 1048576, 2)} MB"
    elif size > 1024:
        return f"{round(size / 1024, 2)} KB"
    else:
        return f"{size} B"
