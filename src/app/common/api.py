"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import random
import uuid

import requests

from ..api.session import NetSession
from ..service.auth_service import AuthService
from ..service.download_service import DownloadService
from ..service.file_service import FileService
from ..service.share_service import ShareService
from ..service.upload_service import UploadService
from .const import all_device_type, all_os_versions, VERSION
from .log import get_logger

logger = get_logger(__name__)


class Pan123:
    """123云盘API客户端类（向后兼容包装层）。

    内部使用服务类处理具体业务逻辑，保持与旧版代码 100% 兼容的公开接口。
    """

    def __init__(
        self,
        readfile=True,
        user_name="",
        password="",
        authorization="",
        input_pwd=False,
        anonymous=False,
    ):
        self._session = NetSession()

        self._auth = AuthService(self._session)
        self._file = FileService(self._session)
        self._download = DownloadService(self._session)
        self._upload = UploadService(self._session)
        self._share = ShareService(self._session)

        self.devicetype = random.choice(all_device_type)
        self.osversion = random.choice(all_os_versions)
        self.loginuuid = uuid.uuid4().hex
        # 保持登录：为 True 时持久化凭证（密码/token），下次启动自动登录
        self.stay_logged_in = True

        # 目录浏览状态
        self.list = []
        self.total = 0
        self.all_file = False
        self.file_page = 0
        self.parent_file_id = 0
        # pan.list 当前所属目录 ID（切换目录时重置，防止内存无限增长）
        self._list_dir_id = None

        if anonymous:
            # 匿名会话：不加载配置、不自动登录，仅用于扫码登录流程
            self.user_name = ""
            self.password = ""
            self.authorization = ""
            self._sync_to_session()
            return

        if readfile:
            self._auth.read_ini(user_name, password, input_pwd, authorization)
            self._sync_from_auth()
        else:
            if not authorization and (user_name == "" or password == ""):
                raise Exception("用户名或密码为空")
            self._auth.user_name = user_name
            self._auth.password = password
            self._auth.authorization = authorization
            self._sync_from_auth()

        self._sync_to_session()
        # 无账号密码（如扫码登录仅凭 token）时跳过自动登录与目录加载
        if self.user_name and self.password:
            res_code_getdir = self.get_dir()[0]
            if res_code_getdir != 0:
                self.login()
                self.get_dir()

    def _sync_to_session(self):
        self._auth.devicetype = self.devicetype
        self._auth.osversion = self.osversion
        self._auth.loginuuid = self.loginuuid
        self._auth.user_name = self.user_name
        self._auth.password = self.password
        self._auth.authorization = self.authorization
        self._auth.stay_logged_in = self.stay_logged_in
        self._auth.sync_to_session()

    def _sync_from_auth(self):
        self.devicetype = self._auth.devicetype
        self.osversion = self._auth.osversion
        self.loginuuid = self._auth.loginuuid
        self.user_name = self._auth.user_name
        self.password = self._auth.password
        self.authorization = self._auth.authorization
        self.stay_logged_in = self._auth.stay_logged_in

    def login(self):
        logger.info("Pan123.login: user=%s", self.user_name)
        self._auth.user_name = self.user_name
        self._auth.password = self.password
        code = self._auth.login()
        if code == 200:
            self.authorization = self._auth.authorization
            self.save_file()
        return code

    def get_user_info(self):
        """获取当前用户的云盘信息（UID、空间、VIP等）。

        Returns:
            ApiReturnModel，成功时 data 为 CloudUserInfoModel 实例
        """
        return self._auth.get_user_info()

    def get_device_list(self):
        """获取当前账户的登录设备列表。

        Returns:
            ApiReturnModel，成功时 data 为 DeviceListResponse 实例
        """
        return self._auth.get_device_list()

    def save_file(self):
        self._auth.devicetype = self.devicetype
        self._auth.osversion = self.osversion
        self._auth.loginuuid = self.loginuuid
        self._auth.user_name = self.user_name
        self._auth.password = self.password
        self._auth.authorization = self.authorization
        self._auth.stay_logged_in = self.stay_logged_in
        self._auth.save_file()

    # ---- 二维码登录 ----

    def qr_generate(self):
        """获取二维码登录会话（uniID + url）。"""
        return self._auth.qr_generate()

    def qr_poll(self, uni_id):
        """轮询二维码扫码状态。"""
        return self._auth.qr_poll(uni_id)

    def qr_wx_code(self, uni_id):
        """获取微信扫码登录凭证（wxCode）。"""
        return self._auth.qr_wx_code(uni_id)

    def apply_saved_device(self):
        """从已保存账户恢复设备指纹（扫码登录验证用）。"""
        self._auth.load_saved_device()
        self._sync_from_auth()
        self._sync_to_session()

    def close(self):
        """释放网络会话资源。"""
        self._session.close()

    def get_dir(self, save=True, force_refresh=False):
        return self.get_dir_by_id(self.parent_file_id, save, force_refresh=force_refresh)

    def get_dir_by_id(self, file_id, save=True, all=False, limit=100,
                      force_refresh=False):
        code, items, total, all_file, _ = self._file.get_dir_by_id(
            file_id, page=self.file_page, list_len=len(self.list),
            all=all, limit=limit, force_refresh=force_refresh,
        )
        if code == 2:
            logger.warning("token 过期，正在尝试重新登录")
            login_code = self.login()
            if login_code == 200:
                return self.get_dir_by_id(file_id, save, all, limit, force_refresh)
            logger.error("重新登录失败")
            return code, []
        if code != 0:
            logger.error(
                "获取文件列表失败: file_id=%s, code=%s",
                file_id, code,
            )
            return code, []

        self.total = total
        self.all_file = all_file
        self.file_page += 1
        if save:
            # 切换目录时重置累积列表，避免长期浏览导致内存无限增长
            if self._list_dir_id != file_id:
                self.list.clear()
                self._list_dir_id = file_id
            elif len(self.list) > 5000:
                # 防御性上限：同一目录被反复获取（如多次 mkdir 刷新）时
                self.list.clear()
            # 原地追加，避免 list + list 整体复制（大目录分页时 O(n²) -> O(n)）
            self.list.extend(items)

        return 0, items

    def link_by_fileDetail(self, file_detail, showlink=True):
        return self._download.link_by_fileDetail(file_detail, showlink)

    def delete_file(self, file, by_num=True, operation=True):
        self._file.delete_file(self.list, file, by_num, operation)

    def rename_file(self, file_id, new_name):
        return self._file.rename_file(file_id, new_name)

    def copy_file(self, file_id_list, target_parent_id, source_parent_id=None):
        """复制文件/文件夹到目标目录。

        Args:
            file_id_list: 文件 ID 列表
            target_parent_id: 目标目录 ID（0 表示根目录）
            source_parent_id: 源目录 ID（可选，用于构造完整的 fileList）

        Returns:
            (success, msg)
        """
        return self._file.copy_files(
            file_id_list, target_parent_id, source_parent_id
        )

    def move_file(self, file_id_list, target_parent_id):
        """移动文件/文件夹到目标目录。

        Args:
            file_id_list: 文件 ID 列表
            target_parent_id: 目标目录 ID（0 表示根目录）

        Returns:
            (success, msg)
        """
        return self._file.move_files(file_id_list, target_parent_id)

    def share(self, file_id_list, share_pwd=""):
        return self._file.share(file_id_list, share_pwd)

    def permanent_delete_files(self, file_id_list):
        """从回收站永久删除指定文件"""
        return self._file.permanent_delete_files(file_id_list)

    def up_load(self, file_path, task=None, resume_info=None, session_callback=None,
                num_threads=1, progress_callback=None):
        return self._upload.up_load(
            file_path, self.parent_file_id,
            task=task, resume_info=resume_info, session_callback=session_callback,
            num_threads=num_threads, progress_callback=progress_callback,
        )

    def mark_dir_dirty(self, dir_id):
        """标记目录缓存为脏，下次浏览时强制从服务器刷新。"""
        self._file.mark_dir_dirty(dir_id)

    def mkdir(self, dirname, remakedir=False):
        file_id, err = self._file.mkdir(dirname, self.list, self.parent_file_id, remakedir)
        if file_id is not None:
            self.get_dir()
        return file_id

    # ---- 分享链接管理（门面方法） ----

    def get_free_share_list(self):
        """获取免费分享列表。"""
        return self._share.get_free_share_list()

    def get_pay_share_list(self):
        """获取付费分享列表。"""
        return self._share.get_pay_share_list()

    def delete_share(self, share_id, drive_id=0):
        """删除分享链接。"""
        return self._share.delete_share(share_id, drive_id)

    # ---- Session 配置（门面方法） ----

    def set_download_multi_thread(self, enabled, num_threads=4):
        """启用/关闭多线程分片下载，并设置每个文件的下载线程数。"""
        self._download.set_multi_thread(enabled, num_threads)

    def set_download_speed_limit(self, kbps):
        self._download.set_download_speed_limit(kbps)

    def set_upload_speed_limit(self, kbps):
        self._upload.set_upload_speed_limit(kbps)

    def set_download_proxy(self, proxy_type, host, port, username="", password=""):
        self._download.set_proxy(proxy_type, host, port, username, password)

    def clear_download_proxy(self):
        self._download.clear_proxy()

    def download_file(self, url, file_path, file_size, progress_callback=None,
                      resume_offset=0, cancel_event=None):
        return self._download.download_file(
            url, file_path, file_size, progress_callback, resume_offset, cancel_event
        )


def check_version():
    """获取版本信息"""
    try:
        response = requests.get(
            "https://api.github.com/repos/123pannextgen/123pan/releases/latest",
            timeout=5,
        )
        response.raise_for_status()
        vesion_info = response.json()
        version = "v" + str(VERSION)
        return vesion_info.get("name") == version
    except Exception as e:
        logger.error("获取版本信息出错: %s", e)
        return False
