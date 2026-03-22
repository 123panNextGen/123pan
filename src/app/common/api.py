import concurrent.futures
import hashlib
import json
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

import requests

from .config import ConfigManager
from .const import all_device_type, all_os_versions
from .log import get_logger

logger = get_logger(__name__)


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

        self.cookies = None
        self.recycle_list = None
        self.list = []
        self.total = 0
        self.parent_file_name_list = []
        self.all_file = False
        self.file_page = 0
        self.file_list = []
        self.dir_list = []
        self.name_dict = {}
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
            "host": "www.123pan.com",
            "app-version": "61",
            "x-app-version": "2.4.0",
        }
        self.parent_file_id = 0  # 路径，文件夹的id,0为根目录
        self.parent_file_list = [0]
        res_code_getdir = self.get_dir()[0]
        if res_code_getdir != 0:
            self.login()
            self.get_dir()

    def login(self):
        """登录123云盘账户并获取授权令牌"""
        data = {"type": 1, "passport": self.user_name, "password": self.password}
        login_res = requests.post(
            "https://www.123pan.com/b/api/user/sign_in",
            headers=self.header_logined,
            data=data,
            timeout=(3, 5),
        )

        res_sign = login_res.json()
        res_code_login = res_sign["code"]
        if res_code_login != 200:
            logger.error("code = 1 Error:" + str(res_code_login))
            logger.error(res_sign.get("message", ""))
            return res_code_login
        set_cookies = login_res.headers.get("Set-Cookie", "")
        set_cookies_list = {}

        for cookie in set_cookies.split(";"):
            if "=" in cookie:
                key, value = cookie.strip().split("=", 1)
                set_cookies_list[key] = value
            else:
                set_cookies_list[cookie.strip()] = None

        self.cookies = set_cookies_list

        token = res_sign["data"]["token"]
        self.authorization = "Bearer " + token
        self.header_logined["authorization"] = self.authorization
        self.save_file()
        return res_code_login

    def save_file(self):
        """将账户信息保存到配置文件"""
        try:
            config = ConfigManager.load_config()
            config.update(
                {
                    "userName": self.user_name,
                    "passWord": self.password,
                    "authorization": self.authorization,
                    "deviceType": self.devicetype,
                    "osVersion": self.osversion,
                }
            )
            ConfigManager.save_config(config)
            logger.info("账号已保存")
        except Exception as e:
            logger.error("保存账号失败:", e)

    def get_dir(self, save=True):
        """获取当前目录下的文件列表"""
        return self.get_dir_by_id(self.parent_file_id, save)

    def get_dir_by_id(self, file_id, save=True, all=False, limit=100):
        """按文件夹ID获取文件列表（支持分页）

        Args:
            file_id: 文件夹ID
            save: 是否保存结果到列表
            all: 是否强制获取所有文件
            limit: 每页限制数量
        """
        get_pages = 3
        res_code_getdir = 0
        page = self.file_page * get_pages + 1
        lenth_now = len(self.list)
        if all:
            # 强制获取所有文件
            page = 1
            lenth_now = 0
        lists = []

        total = -1
        times = 0
        while (lenth_now < total or total == -1) and (times < get_pages or all):
            base_url = "https://www.123pan.com/api/file/list/new"
            params = {
                "driveId": 0,
                "limit": limit,
                "next": 0,
                "orderBy": "file_id",
                "orderDirection": "desc",
                "parentFileId": str(file_id),
                "trashed": False,
                "SearchData": "",
                "Page": str(page),
                "OnlyLookAbnormalFile": 0,
            }
            try:
                a = requests.get(
                    base_url, headers=self.header_logined, params=params, timeout=30
                )
            except requests.exceptions.Timeout:
                logger.error(f"请求超时: {base_url}")
                return -1, []
            except requests.exceptions.ConnectionError as e:
                logger.error(f"连接失败: {e}")
                return -1, []
            except requests.exceptions.RequestException as e:
                logger.error(f"请求异常: {e}")
                return -1, []
            text = a.json()
            res_code_getdir = text["code"]
            if res_code_getdir != 0:
                # token 过期时尝试重新登录一次
                if res_code_getdir == 2:
                    logger.warning("token 过期，正在尝试重新登录")
                    login_code = self.login()
                    if login_code == 0 or login_code == 200:
                        return self.get_dir_by_id(file_id, save, all, limit)
                logger.error("code = 2 Error:" + str(res_code_getdir))
                logger.error(text.get("message", ""))
                return res_code_getdir, []
            lists_page = text["data"]["InfoList"]
            lists += lists_page
            total = text["data"]["Total"]
            lenth_now += len(lists_page)
            page += 1
            times += 1
            if times % 5 == 0:
                logger.warning(
                    "警告：文件夹内文件过多：" + str(lenth_now) + "/" + str(total)
                )
                logger.info("为防止对服务器造成影响，暂停3秒")
                time.sleep(3)

        if lenth_now < total:
            logger.warning("文件夹内文件过多：" + str(lenth_now) + "/" + str(total))
            self.all_file = False
        else:
            self.all_file = True
        self.total = total
        self.file_page += 1
        if save:
            self.list = self.list + lists

        return res_code_getdir, lists

    def show(self):
        """显示文件列表信息到日志"""
        if not self.all_file:
            logger.info(f"获取了{len(self.list)}/{self.total}个文件")
        else:
            logger.info(f"获取全部{len(self.list)}个文件")

    def link_by_number(self, file_number, showlink=True):
        """按编号获取文件下载链接"""
        file_detail = self.list[file_number]
        return self.link_by_fileDetail(file_detail, showlink)

    def link_by_fileDetail(self, file_detail, showlink=True):
        """按文件详情获取下载链接"""
        type_detail = file_detail["Type"]

        if type_detail == 1:
            down_request_url = "https://www.123pan.com/a/api/file/batch_download_info"
            down_request_data = {"fileIdList": [{"fileId": int(file_detail["FileId"])}]}

        else:
            down_request_url = "https://www.123pan.com/a/api/file/download_info"
            down_request_data = {
                "driveId": 0,
                "etag": file_detail["Etag"],
                "fileId": file_detail["FileId"],
                "s3keyFlag": file_detail["S3KeyFlag"],
                "type": file_detail["Type"],
                "fileName": file_detail["FileName"],
                "size": file_detail["Size"],
            }

        link_res = requests.post(
            down_request_url,
            headers=self.header_logined,
            data=json.dumps(down_request_data),
            timeout=10,
        )
        link_res_json = link_res.json()
        res_code_download = link_res_json["code"]
        if res_code_download != 0:
            logger.error("获取下载链接失败，返回码: " + str(res_code_download))
            logger.error(link_res_json.get("message", ""))
            return res_code_download
        down_load_url = link_res.json()["data"]["DownloadUrl"]
        next_to_get = requests.get(
            down_load_url, timeout=10, allow_redirects=False
        ).text
        url_pattern = re.compile(r"href='(https?://[^']+)'")
        redirect_url = url_pattern.findall(next_to_get)[0]
        if showlink:
            logger.info(f"获取下载链接成功: {redirect_url}")

        return redirect_url

    def download(self, file_number, download_path="download"):
        """下载文件"""
        file_detail = self.list[file_number]
        if file_detail["Type"] == 1:
            logger.info("开始下载")
            file_name = file_detail["FileName"] + ".zip"
        else:
            file_name = file_detail["FileName"]  # 文件名

        down_load_url = self.link_by_number(file_number, showlink=False)
        if type(down_load_url) == int:
            return
        self.download_from_url(down_load_url, file_name, download_path)

    def download_from_url(self, url, file_name, download_path="download"):
        """从URL下载文件"""
        download_dir = Path(download_path)
        if not download_dir.exists():
            logger.info("创建下载目录")
            download_dir.mkdir(parents=True, exist_ok=True)

        file_path = download_dir / file_name
        temp_path = file_path.with_suffix(file_path.suffix + ".123pan")

        # 如果临时文件存在，删除它（防止之前的不完整下载）
        if temp_path.exists():
            temp_path.unlink()

        down = requests.get(url, stream=True, timeout=10)
        file_size = int(down.headers.get("Content-Length", 0) or 0)

        # 以.123pan后缀下载，下载完成重命名，防止下载中断
        with open(temp_path, "wb") as f:
            for chunk in down.iter_content(8192):
                if chunk:
                    f.write(chunk)

        os.rename(temp_path, file_path)

    def get_all_things(self, id):
        """获取文件夹内所有内容"""
        self.dir_list.remove(id)
        all_list = self.get_dir_by_id(id, save=False)[1]

        for i in all_list:
            if i["Type"] == 0:
                self.file_list.append(i)
            else:
                self.dir_list.append(i["FileId"])
                self.name_dict[i["FileId"]] = i["FileName"]

        for i in self.dir_list:
            self.get_all_things(i)

    def download_dir(self, file_detail, download_path_root="download"):
        """下载文件夹"""
        self.name_dict[file_detail["FileId"]] = file_detail["FileName"]
        if file_detail["Type"] != 1:
            logger.warning("不是文件夹")
            return

        all_list = self.get_dir_by_id(
            file_detail["FileId"], save=False, all=True, limit=100
        )[1]
        for i in all_list[::-1]:
            if i["Type"] == 0:  # 直接开始下载
                AbsPath = i["AbsPath"]
                for key, value in self.name_dict.items():
                    AbsPath = AbsPath.replace(str(key), value)
                download_path = download_path_root + AbsPath
                download_path = download_path.replace("/" + str(i["FileId"]), "")
                self.download_from_url(i["DownloadUrl"], i["FileName"], download_path)

            else:
                self.download_dir(i, download_path_root)

    def recycle(self):
        """获取回收站列表"""
        recycle_id = 0
        url = (
            "https://www.123pan.com/a/api/file/list/new?driveId=0&limit=100&next=0"
            "&orderBy=fileId&orderDirection=desc&parentFileId="
            + str(recycle_id)
            + "&trashed=true&&Page=1"
        )
        recycle_res = requests.get(url, headers=self.header_logined, timeout=10)
        json_recycle = recycle_res.json()
        recycle_list = json_recycle["data"]["InfoList"]
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
            if file in self.list:
                file_detail = file
            else:
                raise ValueError("文件不存在")
        data_delete = {
            "driveId": 0,
            "fileTrashInfoList": file_detail,
            "operation": operation,
        }
        delete_res = requests.post(
            "https://www.123pan.com/a/api/file/trash",
            data=json.dumps(data_delete),
            headers=self.header_logined,
            timeout=10,
        )
        dele_json = delete_res.json()
        logger.debug(f"删除文件响应: {dele_json}")
        message = dele_json.get("message", "")
        logger.info(f"删除文件消息: {message}")

    def rename_file(self, file_id, new_name):
        """重命名文件或文件夹

        Args:
            file_id: 文件或文件夹的ID
            new_name: 新的文件名

        Returns:
            bool: 是否成功
        """
        data = {"driveId": 0, "fileId": file_id, "fileName": new_name}
        rename_res = requests.post(
            "https://www.123pan.com/a/api/file/rename",
            data=json.dumps(data),
            headers=self.header_logined,
            timeout=10,
        )
        rename_json = rename_res.json()
        code = rename_json.get("code", -1)
        logger.debug(f"重命名文件响应: {rename_json}")
        if code != 0:
            message = rename_json.get("message", "")
            logger.error(f"重命名失败: {message}")
            return False
        logger.info(f"重命名成功: {new_name}")
        return True

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
        share_res = requests.post(
            "https://www.123pan.com/a/api/share/create",
            headers=self.header_logined,
            data=json.dumps(data),
            timeout=10,
        )
        share_res_json = share_res.json()
        if share_res_json.get("code", -1) != 0:
            raise RuntimeError(f"分享失败: {share_res_json.get('message', '')}")
        share_key = share_res_json["data"]["ShareKey"]
        share_url = "https://www.123pan.com/s/" + share_key
        return share_url

    def up_load(self, file_path):
        """上传文件"""
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_path_obj = Path(file_path)
        file_name = file_path_obj.name
        if not file_path_obj.exists():
            raise FileNotFoundError("文件不存在")
        if file_path_obj.is_dir():
            raise IsADirectoryError("不支持文件夹上传")
        fsize = file_path_obj.stat().st_size
        readable_hash = self._compute_file_md5(file_path)

        list_up_request = {
            "driveId": 0,
            "etag": readable_hash,
            "fileName": file_name,
            "parentFileId": self.parent_file_id,
            "size": fsize,
            "type": 0,
            "duplicate": 0,
        }

        up_res = requests.post(
            "https://www.123pan.com/b/api/file/upload_request",
            headers=self.header_logined,
            data=list_up_request,
            timeout=10,
        )
        up_res_json = up_res.json()
        res_code_up = up_res_json.get("code", -1)
        if res_code_up == 5060:
            # 同名文件处理由调用者在GUI中处理
            raise RuntimeError("同名文件存在")
        if res_code_up != 0:
            raise RuntimeError(f"上传请求失败: {up_res_json}")
        up_file_id = up_res_json["data"]["FileId"]
        if up_res_json["data"].get("Reuse", False):
            return up_file_id

        bucket = up_res_json["data"]["Bucket"]
        storage_node = up_res_json["data"]["StorageNode"]
        upload_key = up_res_json["data"]["Key"]
        upload_id = up_res_json["data"]["UploadId"]
        up_file_id = up_res_json["data"][
            "FileId"
        ]  # 上传文件的fileId,完成上传后需要用到

        # 获取已将上传的分块
        start_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        start_res = requests.post(
            "https://www.123pan.com/b/api/file/s3_list_upload_parts",
            headers=self.header_logined,
            data=json.dumps(start_data),
            timeout=10,
        )
        start_res_json = start_res.json()
        res_code_up = start_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"获取传输列表失败: {start_res_json}")

        # 分块，每一块取一次链接，依次上传
        block_size = 5242880
        with open(file_path, "rb") as f:
            part_number_start = 1
            put_size = 0
            while True:
                data = f.read(block_size)
                put_size = put_size + len(data)

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

                get_link_url = (
                    "https://www.123pan.com/b/api/file/s3_repare_upload_parts_batch"
                )
                get_link_res = requests.post(
                    get_link_url,
                    headers=self.header_logined,
                    data=json.dumps(get_link_data),
                    timeout=10,
                )
                get_link_res_json = get_link_res.json()
                res_code_up = get_link_res_json.get("code", -1)
                if res_code_up != 0:
                    raise RuntimeError(f"获取链接失败: {get_link_res_json}")
                upload_url = get_link_res_json["data"]["presignedUrls"][
                    str(part_number_start)
                ]
                requests.put(upload_url, data=data, timeout=10)

                part_number_start = part_number_start + 1

        uploaded_list_url = "https://www.123pan.com/b/api/file/s3_list_upload_parts"
        uploaded_comp_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        requests.post(
            uploaded_list_url,
            headers=self.header_logined,
            data=json.dumps(uploaded_comp_data),
            timeout=10,
        )
        compmultipart_up_url = (
            "https://www.123pan.com/b/api/file/s3_complete_multipart_upload"
        )
        requests.post(
            compmultipart_up_url,
            headers=self.header_logined,
            data=json.dumps(uploaded_comp_data),
            timeout=10,
        )

        if fsize > 64 * 1024 * 1024:
            time.sleep(3)
        close_up_session_url = "https://www.123pan.com/b/api/file/upload_complete"
        close_up_session_data = {"fileId": up_file_id}
        close_up_session_res = requests.post(
            close_up_session_url,
            headers=self.header_logined,
            data=json.dumps(close_up_session_data),
            timeout=10,
        )
        close_res_json = close_up_session_res.json()
        res_code_up = close_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"上传完成确认失败: {close_res_json}")
        return up_file_id

    def cd(self, dir_num):
        """进入文件夹"""
        if dir_num == "..":
            if len(self.parent_file_list) > 1:
                self.all_file = False
                self.file_page = 0
                self.parent_file_list.pop()
                self.parent_file_id = self.parent_file_list[-1]
                self.list = []
                self.parent_file_name_list.pop()
                self.get_dir()
            else:
                raise RuntimeError("已经是根目录")
            return
        if dir_num == "/":
            self.all_file = False
            self.file_page = 0
            self.parent_file_id = 0
            self.parent_file_list = [0]
            self.list = []
            self.parent_file_name_list = []
            self.get_dir()
            return
        if not str(dir_num).isdigit():
            raise ValueError("文件夹编号必须是数字")
        dir_num = int(dir_num) - 1
        if dir_num > (len(self.list) - 1) or dir_num < 0:
            raise IndexError("文件夹编号超出范围")
        if self.list[dir_num]["Type"] != 1:
            raise TypeError("选中项不是文件夹")
        self.all_file = False
        self.file_page = 0
        self.parent_file_id = self.list[dir_num]["FileId"]
        self.parent_file_list.append(self.parent_file_id)
        self.parent_file_name_list.append(self.list[dir_num]["FileName"])
        self.list = []
        self.get_dir()

    def cdById(self, file_id):
        """按ID进入文件夹"""
        self.all_file = False
        self.file_page = 0
        self.list = []
        self.parent_file_id = file_id
        self.parent_file_list.append(self.parent_file_id)
        self.get_dir()
        self.show()

    def read_ini(
        self,
        user_name,
        password,
        input_pwd,
        authorization="",
    ):
        """从配置文件读取账号信息"""
        try:
            config = ConfigManager.load_config()
            deviceType = config.get("deviceType", "")
            osVersion = config.get("osVersion", "")
            loginuuid = config.get("loginuuid", "")
            if deviceType:
                self.devicetype = deviceType
            if osVersion:
                self.osversion = osVersion
            if loginuuid:
                self.loginuuid = loginuuid
            user_name = config.get("userName", user_name)
            password = config.get("passWord", password)
            authorization = config.get("authorization", authorization)
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

        url = "https://www.123pan.com/a/api/file/upload_request"
        data_mk = {
            "driveId": 0,
            "etag": "",
            "fileName": dirname,
            "parentFileId": self.parent_file_id,
            "size": 0,
            "type": 1,
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }
        res_mk = requests.post(
            url, headers=self.header_logined, data=json.dumps(data_mk), timeout=10
        )
        try:
            res_json = res_mk.json()
        except json.decoder.JSONDecodeError:
            logger.error("创建失败")
            logger.error(res_mk.text)
            return
        code_mkdir = res_json.get("code", -1)

        if code_mkdir == 0:
            logger.info(f"创建成功: {res_json['data']['FileId']}")
            self.get_dir()
            return res_json["data"]["Info"]["FileId"]
        logger.error(f"创建失败: {res_json}")
        return

    @staticmethod
    def _compute_file_md5(file_path):
        """计算文件MD5值"""
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(64 * 1024)
                if not data:
                    break
                md5.update(data)
        return md5.hexdigest()

    def stream_download_by_number(
        self, file_number, download_dir, task_id=None, signals=None, task=None
    ):
        file_detail = self.list[file_number]
        if file_detail["Type"] == 1:
            redirect_url = self.link_by_fileDetail(file_detail, showlink=False)
        else:
            redirect_url = self.link_by_number(file_number, showlink=False)
        if isinstance(redirect_url, int):
            raise RuntimeError("获取下载链接失败，返回码: " + str(redirect_url))
        if file_detail["Type"] == 1:
            fname = file_detail["FileName"] + ".zip"
        else:
            fname = file_detail["FileName"]

        out_path = Path(download_dir) / fname
        temp = out_path.with_suffix(out_path.suffix + ".123pan")

        Path(download_dir).mkdir(parents=True, exist_ok=True)

        if out_path.exists():
            # 由调用者决定覆盖行为
            raise FileExistsError(str(out_path))

        total = 0
        accept_ranges = False
        try:
            head = requests.head(redirect_url, allow_redirects=True, timeout=30)
            head.raise_for_status()
            total = int(head.headers.get("Content-Length", 0) or 0)
            accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"
        except Exception:
            try:
                with requests.get(redirect_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0) or 0)
                    accept_ranges = (
                        r.headers.get("Accept-Ranges", "").lower() == "bytes"
                    )
            except Exception:
                total = 0
                accept_ranges = False

        try:
            if accept_ranges and total and total > 1024 * 1024 * 2:
                # 支持配置的线程数,默认最大8线程
                from .config import ConfigManager

                max_download_threads = ConfigManager.get_setting(
                    "maxDownloadThreads", 8
                )
                max_download_threads = min(
                    max(1, int(max_download_threads)), 16
                )  # 限制在1-16之间

                # 根据文件大小动态调整线程数
                num_threads = min(
                    max_download_threads,
                    max(1, int(total / (10 * 1024 * 1024))),  # 每10MB使用一个线程
                )

                # 动态调整 chunk_size
                chunk_size = min(
                    1024 * 1024, max(8192, total // (num_threads * 100))
                )  # 8KB - 1MB

                part_size = total // num_threads
                downloaded = [0]
                dl_lock = threading.Lock()
                last_progress_time = [0]  # 用于控制进度更新频率

                def download_range(start, end, index):
                    part_path = Path(str(temp) + f".part{index}")
                    headers = {"Range": f"bytes={start}-{end}"}
                    try:
                        with requests.get(
                            redirect_url, headers=headers, stream=True, timeout=30
                        ) as r:
                            r.raise_for_status()
                            with open(part_path, "wb") as pf:
                                for chunk in r.iter_content(chunk_size=chunk_size):
                                    if task:
                                        try:
                                            task._pause_event.wait()
                                        except Exception:
                                            pass
                                        if task.is_cancelled:
                                            return False
                                    if chunk:
                                        pf.write(chunk)
                                        with dl_lock:
                                            downloaded[0] += len(chunk)
                                            # 限制进度更新频率,避免过于频繁的UI更新
                                            current_time = time.time()
                                            if (
                                                current_time - last_progress_time[0]
                                                > 0.1
                                            ):  # 每100ms更新一次
                                                if total and signals:
                                                    signals.progress.emit(
                                                        int(downloaded[0] * 100 / total)
                                                    )
                                                last_progress_time[0] = current_time
                        return True
                    except requests.exceptions.RequestException as e:
                        logger.error(f"下载分片 {index} 失败: {e}")
                        if part_path.exists():
                            try:
                                part_path.unlink()
                            except OSError:
                                pass
                        return False
                    except Exception as e:
                        logger.error(f"下载分片 {index} 时发生未知错误: {e}")
                        if part_path.exists():
                            try:
                                part_path.unlink()
                            except OSError:
                                pass
                        return False

                futures = []
                try:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=num_threads, thread_name_prefix="download_range"
                    ) as exe:
                        for i in range(num_threads):
                            start = i * part_size
                            end = (
                                (start + part_size - 1)
                                if i < num_threads - 1
                                else (total - 1)
                            )
                            futures.append(exe.submit(download_range, start, end, i))

                        ok = True
                        for f in concurrent.futures.as_completed(futures):
                            if not f.result():
                                ok = False
                                break

                    if not ok:
                        raise RuntimeError("分片下载失败")
                except concurrent.futures.CancelledError:
                    logger.warning("下载任务被取消")
                    raise RuntimeError("下载任务被取消")

                if task and task.is_cancelled:
                    for i in range(num_threads):
                        p = Path(str(temp) + f".part{i}")
                        if p.exists():
                            try:
                                p.unlink()
                            except OSError:
                                pass
                    return "已取消"

                # 合并分片文件,使用更高效的方式
                try:
                    with open(temp, "wb") as out_f:
                        for i in range(num_threads):
                            p = Path(str(temp) + f".part{i}")
                            try:
                                with open(p, "rb") as pf:
                                    while True:
                                        chunk = pf.read(1024 * 1024)  # 使用更大的缓冲区
                                        if not chunk:
                                            break
                                        out_f.write(chunk)
                                p.unlink()
                            except OSError as e:
                                logger.error(f"合并分片文件 {i} 时出错: {e}")
                                if p.exists():
                                    try:
                                        p.unlink()
                                    except OSError:
                                        pass
                                raise RuntimeError(f"合并分片文件失败: {e}")
                except OSError as e:
                    logger.error(f"创建临时文件时出错: {e}")
                    raise RuntimeError("合并分片文件失败")

                if task and task.is_cancelled:
                    if temp.exists():
                        try:
                            temp.unlink()
                        except OSError:
                            pass
                    return "已取消"

                temp.replace(out_path)
                return out_path
            else:
                with requests.get(redirect_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    done = 0
                    with open(temp, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if task:
                                try:
                                    task._pause_event.wait()
                                except Exception:
                                    pass
                                if task.is_cancelled:
                                    f.close()
                                    if temp.exists():
                                        temp.unlink()
                                    return "已取消"
                            if chunk:
                                f.write(chunk)
                                done += len(chunk)
                                if total and signals:
                                    signals.progress.emit(int(done * 100 / total))
                if task and task.is_cancelled:
                    if temp.exists():
                        temp.unlink()
                    return "已取消"
                temp.replace(out_path)
                return out_path
        except Exception:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
            raise

    def upload_file_stream(
        self, file_path, dup_choice=1, task_id=None, signals=None, task=None
    ):
        """上传文件（分块），支持 progress 回调 与 取消/暂停 控制。

        与 MainWindow 的 ThreadedTask 接口兼容。
        """
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_path_obj = Path(file_path)
        file_name = file_path_obj.name
        if not file_path_obj.exists():
            raise FileNotFoundError("文件不存在")
        if file_path_obj.is_dir():
            raise IsADirectoryError("不支持文件夹上传")
        fsize = file_path_obj.stat().st_size

        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(64 * 1024)
                if not data:
                    break
                md5.update(data)
                if task and task.is_cancelled:
                    return "已取消"
        readable_hash = md5.hexdigest()

        list_up_request = {
            "driveId": 0,
            "etag": readable_hash,
            "fileName": file_name,
            "parentFileId": self.parent_file_id,
            "size": fsize,
            "type": 0,
            "duplicate": 0,
        }
        url = "https://www.123pan.com/b/api/file/upload_request"
        headers = self.header_logined.copy()
        res = requests.post(url, headers=headers, data=list_up_request, timeout=30)
        res_json = res.json()
        code = res_json.get("code", -1)
        if code == 5060:
            list_up_request["duplicate"] = dup_choice
            res = requests.post(
                url, headers=headers, data=json.dumps(list_up_request), timeout=30
            )
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
                get_link_url = (
                    "https://www.123pan.com/b/api/file/s3_repare_upload_parts_batch"
                )
                get_link_res = requests.post(
                    get_link_url,
                    headers=headers,
                    data=json.dumps(get_link_data),
                    timeout=30,
                )
                get_link_res_json = get_link_res.json()
                if get_link_res_json.get("code", -1) != 0:
                    raise RuntimeError(
                        "获取上传链接失败: "
                        + json.dumps(get_link_res_json, ensure_ascii=False)
                    )
                upload_url = get_link_res_json["data"]["presignedUrls"][
                    str(part_number)
                ]
                requests.put(upload_url, data=block, timeout=60)
                total_sent += len(block)
                if signals and fsize:
                    signals.progress.emit(int(total_sent * 100 / fsize))
                part_number += 1
        uploaded_list_url = "https://www.123pan.com/b/api/file/s3_list_upload_parts"
        uploaded_comp_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        requests.post(
            uploaded_list_url,
            headers=headers,
            data=json.dumps(uploaded_comp_data),
            timeout=30,
        )
        compmultipart_up_url = (
            "https://www.123pan.com/b/api/file/s3_complete_multipart_upload"
        )
        requests.post(
            compmultipart_up_url,
            headers=headers,
            data=json.dumps(uploaded_comp_data),
            timeout=30,
        )
        if fsize > 64 * 1024 * 1024:
            time.sleep(3)
        close_up_session_url = "https://www.123pan.com/b/api/file/upload_complete"
        close_up_session_data = {"fileId": up_file_id}
        close_res = requests.post(
            close_up_session_url,
            headers=headers,
            data=json.dumps(close_up_session_data),
            timeout=30,
        )
        cr = close_res.json()
        if cr.get("code", -1) != 0:
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


class TransferTask:
    """传输任务的数据模型"""

    def __init__(self, task_id, task_type, name, size):
        self.id = task_id
        self.type = task_type  # "上传" 或 "下载"
        self.name = name
        self.size = size
        self.progress = 0
        self.status = "等待中"
        self.file_path = None
        self.threaded_task = None
        self.is_paused = False

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "size": self.size,
            "progress": self.progress,
            "status": self.status,
            "file_path": self.file_path,
        }


class TransferTaskManager:
    """传输任务管理器 - 仅处理业务逻辑，不涉及UI"""

    def __init__(self):
        self.tasks = {}
        self.next_task_id = 0
        self.lock = threading.Lock()

    def create_task(self, task_type, name, size):
        """创建新任务并返回task_id"""
        with self.lock:
            task_id = self.next_task_id
            self.next_task_id += 1
            self.tasks[task_id] = TransferTask(task_id, task_type, name, size)
        return task_id

    def get_task(self, task_id):
        """获取指定任务"""
        return self.tasks.get(task_id)

    def update_task_progress(self, task_id, progress):
        """更新任务进度"""
        task = self.get_task(task_id)
        if task:
            task.progress = max(0, min(100, progress))

    def update_task_status(self, task_id, status):
        """更新任务状态"""
        task = self.get_task(task_id)
        if task:
            task.status = status

    def update_task(self, task_id, progress=None, status=None):
        """更新任务（进度和/或状态）"""
        task = self.get_task(task_id)
        if task:
            if progress is not None:
                task.progress = max(0, min(100, progress))
            if status is not None:
                task.status = status

    def cancel_task(self, task_id):
        """取消任务"""
        task = self.get_task(task_id)
        if task:
            task.status = "已取消"
            if task.threaded_task:
                try:
                    task.threaded_task.cancel()
                except:
                    pass
            return True
        return False

    def pause_task(self, task_id):
        """暂停任务"""
        task = self.get_task(task_id)
        if task and task.threaded_task:
            try:
                task.threaded_task.pause()
                task.status = "已暂停"
                task.is_paused = True
                return True
            except:
                pass
        return False

    def resume_task(self, task_id):
        """恢复任务"""
        task = self.get_task(task_id)
        if task and task.threaded_task:
            try:
                task.threaded_task.resume()
                task.status = "下载中" if task.type == "下载" else "上传中"
                task.is_paused = False
                return True
            except:
                pass
        return False

    def remove_task(self, task_id):
        """移除任务"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False

    def get_all_tasks(self):
        """获取所有任务"""
        return list(self.tasks.values())

    def clear_completed_tasks(self):
        """清除已完成的任务"""
        to_remove = [
            task_id
            for task_id, task in self.tasks.items()
            if task.status in ("已完成", "已取消", "失败")
        ]
        for task_id in to_remove:
            del self.tasks[task_id]


class FileDataManager:
    """文件数据处理器 - 处理与文件相关的业务逻辑，不涉及UI"""

    @staticmethod
    def get_file_type_name(file_type):
        """根据文件类型返回类型名称"""
        return "文件夹" if file_type == 1 else "文件"

    @staticmethod
    def format_file_size_value(size):
        """格式化文件大小（工具函数别名）"""
        return format_file_size(size)

    @staticmethod
    def get_file_extension(filename):
        """获取文件扩展名"""
        return Path(filename).suffix.lower()

    @staticmethod
    def validate_file_exists(file_path):
        """验证文件是否存在"""
        return Path(file_path).is_file()

    @staticmethod
    def is_duplicate_filename(pan_instance, filename):
        """检查是否存在同名文件"""
        return any(item.get("FileName") == filename for item in pan_instance.list)
